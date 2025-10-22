import socket
import threading
import time
import os
import random
import queue
import RPi.GPIO as GPIO
import pigpio
from PIL import Image, ImageSequence, ImageOps
from drive import SSD1305

# ======== PINS / CONSTANTS ========
IN1 = 22            # H-bridge input for motor direction
IN2 = 23            # H-bridge input for motor direction
PWM_A = 4           # PWM pin for motor speed
SERVO_PIN = 12      # BCM 12 for steering
LED_PIN = 5         # LED Headlights
PWM_FREQ = 100      # Hz for DC motor PWM
FACES_DIR = "./ReactionGifs"
FRAME_UPDATE = 0.08 # s for quick face animations
IDLE_INTERVAL = 2.0  # seconds between idle actions
FALLBACK_FRAME_MS = 80  # if GIF has no per-frame duration
MAX_STEER_DEG = 15  # max servo angle either direction (degrees)

# ======== FACE MANAGER ========
class FaceManager:
    def __init__(self, disp):
        self.disp = disp
        self.disp.Init()
        self._gif_cache = {}  # {name: [(img, dt_sec), ...]}
        self.last_happy_face = None  # Track last happy face
        self.last_sad_face = None    # Track last sad face

        # Preload needed gifs
        self._ensure_gif("Blink.gif")
        self._ensure_gif("LeftRight.gif")
        self._ensure_gif("Right-star.gif")
        self._ensure_gif("Right-slotmachine.gif")
        self._ensure_gif("Wrong-Shake.gif")
        self._ensure_gif("Wrong-x.gif")

    def _prep(self, img):
        if img.size != (self.disp.width, self.disp.height):
            img = ImageOps.fit(img, (self.disp.width, self.disp.height), method=Image.BICUBIC)
        if img.mode != '1':
            img = img.convert('L').convert('1')
        return img

    def show_image(self, img):
        img = self._prep(img)
        self.disp.getbuffer(img)
        self.disp.ShowImage()

    def _ensure_gif(self, name):
        if name in self._gif_cache:
            return True
        path = os.path.join(FACES_DIR, name)
        if not os.path.isfile(path):
            print(f"[FaceManager] GIF not found: {path}")
            return False
        im = Image.open(path)
        bg = Image.new("RGBA", im.size, (0,0,0,0))
        frames = []
        for raw in ImageSequence.Iterator(im):
            fr = bg.copy()
            fr.alpha_composite(raw.convert("RGBA"))
            dur = raw.info.get("duration", FALLBACK_FRAME_MS) / 1000.0
            frames.append((fr.copy(), max(0.001, dur)))
            bg = fr
        if frames:
            self._gif_cache[name] = frames
            return True
        print(f"[FaceManager] Failed to load GIF: {name}")
        return False

    def play_gif_blocking(self, name, repeat=1):
        print(f"[FaceManager] Playing GIF: {name}, repeat={repeat}")
        if not self._ensure_gif(name):
            print(f"[FaceManager] GIF not available: {name}")
            return False
        frames = self._gif_cache[name]
        for _ in range(max(1, int(repeat))):
            for img, dt in frames:
                self.show_image(img)
                time.sleep(dt)
        print(f"[FaceManager] Finished playing GIF: {name}")
        return True

    def first_frame(self, name):
        if not self._ensure_gif(name):
            print(f"[FaceManager] No first frame for GIF: {name}")
            return None
        return self._gif_cache[name][0][0]

# ======== BEHAVIOR RUNNER ========
class BehaviorRunner:
    def __init__(self, faces, car):
        self.faces = faces
        self.car = car
        self.q = queue.Queue()
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def stop(self):
        print("[BehaviorRunner] Stopping...")
        self._stop.set()
        self.q.put(None)

    def enqueue(self, fn):
        print("[BehaviorRunner] Enqueuing new behavior")
        self.q.put(fn)

    def _idle_once(self):
        print("[BehaviorRunner] Performing idle cycle")
        first = self.faces.first_frame("Blink.gif")
        if first is not None:
            self.faces.show_image(first)
        time.sleep(IDLE_INTERVAL)

        if random.random() < 0.5:
            played = self.faces.play_gif_blocking("Blink.gif", repeat=1)
            if not played and first is not None:
                self.faces.show_image(first)
        else:
            played = self.faces.play_gif_blocking("LeftRight.gif", repeat=1)
            if not played and first is not None:
                self.faces.show_image(first)

        if first is not None:
            self.faces.show_image(first)

    def _loop(self):
        print("[BehaviorRunner] Starting loop")
        first = self.faces.first_frame("Blink.gif")
        if first is not None:
            self.faces.show_image(first)

        while not self._stop.is_set():
            try:
                job = self.q.get(timeout=0.1)
            except queue.Empty:
                self._idle_once()
                continue

            if job is None or self._stop.is_set():
                print("[BehaviorRunner] Exiting loop")
                break

            try:
                job()
            except Exception as e:
                print(f"[BehaviorRunner] Job error: {e}")
            finally:
                self.q.task_done()

# ======== CAR HARDWARE MANAGER ========
class CarHW:
    def __init__(self):
        print("[CarHW] Initializing hardware")
        GPIO.setmode(GPIO.BCM)
        GPIO.setwarnings(False)

        # LED setup (default on)
        GPIO.setup(LED_PIN, GPIO.OUT, initial=GPIO.HIGH)

        # Motor H-bridge setup
        GPIO.setup(IN1, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(IN2, GPIO.OUT, initial=GPIO.LOW)
        GPIO.setup(PWM_A, GPIO.OUT)
        self.power_a = GPIO.PWM(PWM_A, PWM_FREQ)
        self.power_a.start(0)  # Start PWM at 0% duty cycle

        # Servo via pigpio
        self.pi = pigpio.pi()
        if not self.pi.connected:
            print("[CarHW] ERROR: pigpio daemon not running")
            raise RuntimeError("pigpio daemon not running")

        # OLED faces
        self.disp = SSD1305.SSD1305()
        self.faces = FaceManager(self.disp)

        # Single behavior runner
        self.runner = BehaviorRunner(self.faces, self)

    # Servo motor (steering) helpers
    def angle_to_us(self, a_deg: float) -> int:
        print(f"[CarHW] Converting angle {a_deg} to microseconds")
        a_deg = max(-90, min(90, a_deg))
        return int(1500 + (a_deg / 90.0) * 1000)  # ~500–2500us

    def steer_us(self, usec: int):
        print(f"[CarHW] Steering to {usec}us")
        self.pi.set_servo_pulsewidth(SERVO_PIN, int(usec))

    def steer_deg(self, degrees: float):
        print(f"[CarHW] Steering to {degrees} degrees")
        d = max(-MAX_STEER_DEG, min(MAX_STEER_DEG, float(degrees)))
        self.steer_us(self.angle_to_us(d))

    # Motor control helpers
    def forward(self, speed: int):
        print(f"[CarHW] Motor forward at speed {speed}%")
        speed = max(0, min(100, speed))  # Clamp speed to 0-100
        GPIO.output(IN1, GPIO.HIGH)
        GPIO.output(IN2, GPIO.LOW)
        self.power_a.ChangeDutyCycle(speed)

    def backward(self, speed: int):
        print(f"[CarHW] Motor backward at speed {speed}%")
        speed = max(0, min(100, speed))  # Clamp speed to 0-100
        GPIO.output(IN1, GPIO.LOW)
        GPIO.output(IN2, GPIO.HIGH)
        self.power_a.ChangeDutyCycle(speed)

    def stop(self):
        print("[CarHW] Motor stopped")
        GPIO.output(IN1, GPIO.LOW)
        GPIO.output(IN2, GPIO.LOW)
        self.power_a.ChangeDutyCycle(0)

    def _stop_and_center(self):
        print("[CarHW] Stopping motors and centering steering")
        self.stop()  # Stop motors
        self.steer_deg(0)  # Center steering

    # LED helpers
    def led_on(self):
        print("[CarHW] LED on")
        GPIO.output(LED_PIN, GPIO.HIGH)

    def led_off(self):
        print("[CarHW] LED off")
        GPIO.output(LED_PIN, GPIO.LOW)

    def led_flash(self, times=6, on_ms=80, off_ms=80):
        print(f"[CarHW] Flashing LED: {times} times, {on_ms}ms on, {off_ms}ms off")
        for _ in range(max(1, int(times))):
            GPIO.output(LED_PIN, GPIO.HIGH)
            time.sleep(on_ms/1000.0)
            GPIO.output(LED_PIN, GPIO.LOW)
            time.sleep(off_ms/1000.0)
            GPIO.output(LED_PIN, GPIO.HIGH)  # Return to default on

    # HAPPY behavior
    def happy(self):
        def job():
            print("[CarHW] Executing happy behavior")
            happy_faces = ["Right-star.gif", "Right-slotmachine.gif"]
            choice = happy_faces[0] if self.faces.last_happy_face == happy_faces[1] else happy_faces[1]
            self.faces.last_happy_face = choice

            def face_task():
                self.faces.play_gif_blocking(choice, repeat=1)

            def led_task():
                self.led_flash(times=10, on_ms=50, off_ms=50)

            def motor_task():
                # Left steer, forward, back
                self.steer_deg(15)
                self.forward(50)
                time.sleep(0.5)
                self.stop()
                time.sleep(0.05)  # Brief delay to stabilize
                self.backward(50)
                time.sleep(0.5)
                self.stop()
                time.sleep(0.05)
                # Right steer, forward, back
                self.steer_deg(-15)
                self.forward(50)
                time.sleep(0.5)
                self.stop()
                time.sleep(0.05)
                self.backward(50)
                time.sleep(0.5)
                self.stop()
                time.sleep(0.05)

            # Run tasks concurrently
            threads = [
                threading.Thread(target=face_task),
                threading.Thread(target=led_task),
                threading.Thread(target=motor_task)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self._stop_and_center()
            self.led_on()  # Ensure LEDs are back on
        self.runner.enqueue(job)

    # SAD behavior
    def sad(self):
        def job():
            print("[CarHW] Executing sad behavior")
            sad_faces = ["Wrong-Shake.gif", "Wrong-x.gif"]
            choice = sad_faces[0] if self.faces.last_sad_face == sad_faces[1] else sad_faces[1]
            self.faces.last_sad_face = choice

            def face_task():
                self.faces.play_gif_blocking(choice, repeat=1)

            def led_task():
                self.led_flash(times=1, on_ms=500, off_ms=500)

            def motor_task():
                self.backward(30)
                time.sleep(1.0)
                self.stop()
                time.sleep(0.05)  # Brief delay to stabilize
                self.forward(30)
                time.sleep(1.0)
                self.stop()
                time.sleep(0.05)

            # Run tasks concurrently
            threads = [
                threading.Thread(target=face_task),
                threading.Thread(target=led_task),
                threading.Thread(target=motor_task)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self._stop_and_center()
            self.led_on()  # Ensure LEDs are back on
        self.runner.enqueue(job)

    def idle(self):
        print("[CarHW] Clearing queue for idle behavior")
        pass

    def cleanup(self):
        print("[CarHW] Cleaning up")
        self.runner.stop()
        self.faces.disp.clear()
        self.faces.disp.ShowImage()
        self.pi.set_servo_pulsewidth(SERVO_PIN, 0)
        self.power_a.stop()  # Stop PWM
        self.led_off()
        self.pi.stop()
        GPIO.cleanup()
        print("[CarHW] Cleanup complete")

# ======== COMMAND SERVER ========
HW = None

def init_hardware():
    global HW
    if HW is None:
        HW = CarHW()
    return HW

HOST = "0.0.0.0"
PORT = 5005
SHARED_TOKEN = "monstercookiebrownie"

def handle_command(cmd: str):
    cmd = cmd.strip().upper()
    print(f"[Command] Received: {cmd}")
    if cmd == "RIGHT":
        HW.happy()
        return "OK RIGHT"
    elif cmd == "WRONG":
        HW.sad()
        return "OK SAD"
    elif cmd == "IDLE":
        HW.idle()
        return "OK IDLE"
    elif cmd == "PING":
        return "PONG"
    elif cmd.startswith("FACE "):
        parts = cmd.split()
        name = parts[1] if len(parts) >= 2 else ""
        rep = int(parts[2]) if len(parts) >= 3 and parts[2].isdigit() else 1
        def job():
            HW.faces.play_gif_blocking(name, repeat=rep)
        HW.runner.enqueue(job)
        return "OK FACE"
    else:
        print(f"[Command] Unknown command: {cmd}")
        return "ERR UNKNOWN"

def client_thread(conn, addr):
    with conn:
        conn.settimeout(5)
        data = b""
        try:
            while True:
                chunk = conn.recv(1024)
                if not chunk:
                    break
                data += chunk
                if b"\n" in data:
                    break
        except socket.timeout:
            pass

        msg = data.decode("utf-8", errors="ignore").strip()
        token, payload = "", msg
        if ":" in msg:
            token, payload = msg.split(":", 1)
            token, payload = token.strip(), payload.strip()

        if SHARED_TOKEN and token != SHARED_TOKEN:
            conn.sendall(b"ERR AUTH\n")
            return

        reply = handle_command(payload)
        conn.sendall((reply + "\n").encode("utf-8"))

def serve():
    init_hardware()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(5)
        print(f"[AGENT] Listening on {HOST}:{PORT}")
        try:
            while True:
                conn, addr = s.accept()
                threading.Thread(target=client_thread, args=(conn, addr), daemon=True).start()
        except KeyboardInterrupt:
            pass
        finally:
            HW.cleanup()

if __name__ == "__main__":
    serve()