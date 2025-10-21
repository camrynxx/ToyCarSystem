#!/usr/bin/env python3
import socket, threading, time, os

#!/usr/bin/env python3
# CarHW with ready-to-use HAPPY and SAD reactions
import os, time, threading
import RPi.GPIO as GPIO
import pigpio
from PIL import Image
from drive import SSD1305  # your OLED driver

# ======== PINS / CONSTANTS ========
IN1 = 22            # H-bridge input
IN2 = 23            # H-bridge input
PWM_A = 4           # PWM pin for motor speed
SERVO_PIN = 12      # BCM 12 for steering
PWM_FREQ = 100      # Hz for DC motor PWM
FACES_DIR = "./faces"
FRAME_UPDATE = 0.08 # s for quick face animations

# ======== HELPER: Servo angle to microseconds ========
def angle_to_us(a_deg: float) -> int:
    a_deg = max(-90, min(90, a_deg))
    return int(1500 + (a_deg / 90.0) * 1000)  # 500–2500us

# ======== FACE MANAGER ========
class FaceManager:
    def __init__(self):
        self.disp = SSD1305.SSD1305()
        self.disp.Init()
        self.lock = threading.Lock()
        self.neutral_sequence = [
            "neutral0.png","neutral1.png","neutral2.png",
            "neutral1.png","neutral3.png","neutral1.png","neutral4.png"
        ]
        self._anim_thread = None
        self._stop = threading.Event()
        self.start_neutral()

    def _load(self, name):
        img = Image.open(os.path.join(FACES_DIR, name))
        if img.mode != '1':
            img = img.convert('1')
        if img.size != (self.disp.width, self.disp.height):
            raise ValueError(f"Image must be {self.disp.width}x{self.disp.height}, got {img.size}")
        return img

    def _show(self, name):
        with self.lock:
            img = self._load(name)
            self.disp.getbuffer(img)
            self.disp.ShowImage()

    def start_neutral(self):
        self.stop_anim()
        def runner():
            while not self._stop.is_set():
                for f in self.neutral_sequence:
                    if self._stop.is_set(): break
                    self._show(f)
                    time.sleep(0.5)
        self._stop.clear()
        self._anim_thread = threading.Thread(target=runner, daemon=True)
        self._anim_thread.start()

    def stop_anim(self):
        if self._anim_thread and self._anim_thread.is_alive():
            self._stop.set()
            self._anim_thread.join(timeout=0.5)
        self._stop.clear()

    def flash_face(self, sequence, frame_time=0.12, repeat=1, return_to_neutral=True):
        """Show a short sequence (e.g., happy/sad) then resume neutral."""
        self.stop_anim()
        for _ in range(repeat):
            for f in sequence:
                self._show(f)
                time.sleep(frame_time)
        if return_to_neutral:
            self.start_neutral()

    def clear(self):
        with self.lock:
            self.disp.clear()
            self.disp.ShowImage()

# ======== MOTOR / STEERING ========
class CarHW:
    def __init__(self):
        # GPIO DC motor
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(IN1, GPIO.OUT)
        GPIO.setup(IN2, GPIO.OUT)
        GPIO.setup(PWM_A, GPIO.OUT)
        self.pwm = GPIO.PWM(PWM_A, PWM_FREQ)
        self.pwm.start(0)  # start stopped
        GPIO.output(IN1, GPIO.LOW)
        GPIO.output(IN2, GPIO.LOW)

        # Servo (pigpio daemon must be running)
        self.pi = pigpio.pi()
        if not self.pi.connected:
            raise SystemExit("Start pigpio: sudo systemctl enable --now pigpiod")
        self.center_steering()

        # OLED faces
        self.faces = FaceManager()

    # ---- Low-level motor control ----
    def set_speed(self, duty: float):
        """0..100%"""
        duty = max(0.0, min(100.0, duty))
        self.pwm.ChangeDutyCycle(duty)

    def forward(self, duty=60):
        GPIO.output(IN1, GPIO.HIGH)
        GPIO.output(IN2, GPIO.LOW)
        self.set_speed(duty)

    def backward(self, duty=50):
        GPIO.output(IN1, GPIO.LOW)
        GPIO.output(IN2, GPIO.HIGH)
        self.set_speed(duty)

    def stop(self):
        self.set_speed(0)
        GPIO.output(IN1, GPIO.LOW)
        GPIO.output(IN2, GPIO.LOW)

    # ---- Steering ----
    def set_angle(self, a_deg: float):
        self.pi.set_servo_pulsewidth(SERVO_PIN, angle_to_us(a_deg))

    def center_steering(self):
        self.set_angle(0)

    # ---- Reactions ----
    def happy(self):
        """
        HAPPY = quick wiggle + forward burst, with upbeat face.
        Duration ~1.4s, snappy feel, low latency.
        """
        # Face: blink-smile sequence; adjust names to your files
        happy_seq = ["happy0.png","happy1.png","happy2.png","happy1.png"]
        threading.Thread(target=self.faces.flash_face,
                         args=(happy_seq,),
                         kwargs=dict(frame_time=0.10, repeat=2, return_to_neutral=True),
                         daemon=True).start()

        # Motion: steer wiggle while pulsing forward
        try:
            self.center_steering()
            t0 = time.time()

            # short forward pulse
            self.forward(70); time.sleep(0.25)
            # wiggle left-right with short pulses
            for a in (+25, -25, +20, -20):
                self.set_angle(a)
                self.forward(60); time.sleep(0.18)
                self.stop(); time.sleep(0.05)

            # finish with a confident nudge
            self.center_steering()
            self.forward(65); time.sleep(0.22)
        finally:
            self.stop()
            self.center_steering()

    def wrong(self):
        """
        SAD = slow reverse + head shake, with sad face.
        Duration ~1.6s, clearly different mood.
        """
        sad_seq = ["sad0.png","sad1.png","sad2.png","sad1.png"]
        threading.Thread(target=self.faces.flash_face,
                         args=(sad_seq,),
                         kwargs=dict(frame_time=0.14, repeat=2, return_to_neutral=True),
                         daemon=True).start()

        try:
            # gentle reverse to indicate "oops"
            self.center_steering()
            self.backward(45); time.sleep(0.40)
            self.stop(); time.sleep(0.08)

            # slow “head shake” no + yes (left-right-left)
            for a in (-20, +20, -15):
                self.set_angle(a); time.sleep(0.18)
            self.center_steering(); time.sleep(0.10)

            # tiny forward settle
            self.forward(40); time.sleep(0.20)
        finally:
            self.stop()
            self.center_steering()

    def idle(self):
        """Neutral face & motors off."""
        self.stop()
        self.center_steering()
        self.faces.start_neutral()

    def cleanup(self):
        self.stop()
        self.faces.clear()
        self.pi.set_servo_pulsewidth(SERVO_PIN, 0)  # servo off
        self.pi.stop()
        GPIO.cleanup()
        print("[HW] CLEANUP complete")

HW = None

def init_hardware():
    global HW
    if HW is None:
        HW = CarHW()
    return HW

# ==== COMMAND SERVER ====
HOST = "0.0.0.0"
PORT = 5005
# Optional simple shared secret; set env CAR_AGENT_TOKEN on both sides
SHARED_TOKEN = "monstercookiebrownie"

def handle_command(cmd: str):
    """Reply immediately; do the action in a background thread."""
    if cmd == "RIGHT":
        threading.Thread(target=HW.happy, daemon=True).start()
        return "OK RIGHT"
    elif cmd == "WRONG":
        threading.Thread(target=HW.wrong, daemon=True).start()
        return "OK WRONG"
    elif cmd == "IDLE":
        threading.Thread(target=HW.idle, daemon=True).start()
        return "OK IDLE"
    elif cmd == "PING":
        return "PONG"
    else:
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
        # Expect formats:
        #   RIGHT
        #   token:RIGHT
        token, payload = "", msg
        if ":" in msg:
            token, payload = msg.split(":", 1)
            token, payload = token.strip(), payload.strip()

        if SHARED_TOKEN and token != SHARED_TOKEN:
            conn.sendall(b"ERR AUTH\n")
            return

        reply = handle_command(payload.upper())
        conn.sendall((reply + "\n").encode("utf-8"))

def serve():
    init_hardware()
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((HOST, PORT))
        s.listen(5)
        print(f"[AGENT] listening on {HOST}:{PORT}")
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
