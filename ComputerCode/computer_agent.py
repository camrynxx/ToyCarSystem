import random, torch, whisper, re, string, threading, socket
import tkinter as tk 
import sounddevice as sd
from scipy.io.wavfile import write
from enum import Enum
import queue, time, wave, os
from datetime import datetime
import numpy as np
from word2number import w2n
from PIL import Image, ImageTk

#Setup whisper
whisperModel = whisper.load_model("tiny")

#Setup TTS
language = 'en'
ttsmodel_id = 'v3_en'
device = torch.device('cpu')
ttsmodel, example_text = torch.hub.load(repo_or_dir='snakers4/silero-models',
                                    model='silero_tts',
                                    language=language,
                                    speaker=ttsmodel_id)
ttsmodel.to(device)

#Setup VAD
torch.set_num_threads(1)
vadmodel, utils = torch.hub.load('snakers4/silero-vad', 'silero_vad', trust_repo=True)
vadmodel = vadmodel.to(device).eval()

SAMPLE_RATE = 16000
OUT_DIR = "recording"
os.makedirs(OUT_DIR, exist_ok=True)
q = queue.Queue()

def send_reaction(event: str, host="camrynpi.local", port=5005, token=None, timeout=0.5):
    # Sends a reaction event to a remote host over a socket connection.

    """
    Sends a reaction event to a specified host and port using a socket connection.

    Args:
        event (str): The event string to send.
        host (str, optional): The hostname or IP address of the remote host. Defaults to "camrynpi.local".
        port (int, optional): The port number to connect to. Defaults to 5005.
        token (str, optional): An optional authentication token to prepend to the event. Defaults to None.
        timeout (float, optional): The timeout for the socket connection in seconds. Defaults to 0.5.

    Returns:
        str: "SENT" if the message was sent successfully, or an error string in the format "ERR <ExceptionName>" if an exception occurred.
    """
    msg = f"{token}:{event}\n" if token else f"{event}\n"
    try:
        with socket.create_connection((host, port), timeout=timeout) as s:
            s.sendall(msg.encode())
            # don't block waiting for reply
            return "SENT"
    except Exception as e:
        return f"ERR {e.__class__.__name__}"

def audio_cb(indata, frames, time_info, status):
    """
    Callback function for sounddevice.InputStream.
    Receives audio input chunks and puts them into a queue for processing.
    """
    if status: print("sd status:", status)
    # indata: int16, shape (frames, channels)
    q.put(indata.copy())

def write_wav_int16(path, samples_int16, sr=SAMPLE_RATE):
    """
    Writes int16 audio samples to a WAV file at the specified path and sample rate.
    """
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(samples_int16.tobytes())

class QuestionType(Enum):
    # This enum class defines different types of questions that can be used in the application.
    """
    QuestionType is an enumeration representing the types of questions supported by the system.

    Members:
        COUNTAFTER: Represents a question type that counts items after a certain condition.
        GREATER: Represents a question type that compares if a value is greater than another.
        ADD: Represents a question type that performs addition.
        ADDOBJECTS: Represents a question type that adds objects together.
    """
    COUNTAFTER = 1
    GREATER = 2
    ADD = 3
    ADDOBJECTS = 4

def number_to_words(n):
    # Converts a single-digit integer to its English word representation.
    """
    Convert a single-digit integer to its corresponding English word.

    Parameters:
        n (int): A single-digit integer (1-9).

    Returns:
        str: The English word for the digit if n is between 1 and 9, otherwise the string representation of n.
    """
    words = {
        1: "one", 2: "two", 3: "three", 4: "four", 5: "five",
        6: "six", 7: "seven", 8: "eight", 9: "nine"
    }
    return words.get(n, str(n))

def generate_question(question_type):
    """
    Generates a math-related question and its answer based on the specified question type.

    The function supports the following question types:
        - COUNTAFTER: Asks for the number that comes after a given number.
        - GREATER: Asks which of two numbers is greater.
        - ADD: Asks for the sum of two numbers.
        - ADDOBJECTS: Asks for the sum of two groups of objects.

    Args:
        question_type (QuestionType): The type of question to generate.

    Returns:
        tuple: A tuple containing the generated question (str) and its answer (str).

    # This function creates simple math questions for children and returns both the question and the correct answer.
    """
    if question_type == QuestionType.COUNTAFTER:
        number = random.randint(1, 8)  # so number+1 <= 9
        question = f"What is the number that comes after {number_to_words(number)}?"
        answer = number_to_words(number + 1)
    elif question_type == QuestionType.GREATER:
        nums = random.sample(range(1, 10), 2)
        question = f"What number is greater: {number_to_words(nums[0])}, or {number_to_words(nums[1])}?"
        answer = number_to_words(max(nums))
    elif question_type == QuestionType.ADD:
        number1 = random.randint(1, 8)
        number2 = random.randint(1, 9 - number1)  # so sum <= 9
        question = f"What is {number_to_words(number1)}, plus {number_to_words(number2)}?"
        answer = number_to_words(number1 + number2)
    elif question_type == QuestionType.ADDOBJECTS:
        objects = ["apples", "oranges", "strawberries"]
        chosen_object = random.choice(objects)
        number1 = random.randint(1, 8)
        number2 = random.randint(1, 9 - number1)  # so sum <= 9
        question = f"What is {number_to_words(number1)} {chosen_object}, plus {number_to_words(number2)} {chosen_object}?"
        total = number1 + number2
        answer = f"{number_to_words(total)}"
    return question, answer

class CarGUIApp:
    def __init__(self, master):
        """
        Initializes the main GUI window for the Toy Car Buddy application.

        Sets up the window properties, layout containers, title, car image, output area,
        status label, and the "Ask me a question!" button. Also initializes recording parameters.

        Args:
            master (tk.Tk): The root Tkinter window.

        # This function sets up the initial state and layout of the Toy Car Buddy GUI.
        """
        self.master = master
        self.master.title("Toy Car Buddy")
        self.master.geometry("480x560")
        self.master.configure(bg="#2C3E50")

        # Layout containers
        self.top = tk.Frame(master, bg="#2C3E50")
        self.top.pack(fill="x", pady=(16, 8))

        self.mid = tk.Frame(master, bg="#2C3E50")
        self.mid.pack(expand=True, fill="both", pady=(4, 8))

        self.bottom = tk.Frame(master, bg="#2C3E50")
        self.bottom.pack(fill="x", pady=(0, 16))

        # Title
        self.title = tk.Label(self.top, text="Toy Car Buddy",
                              font=("Helvetica", 22, "bold"),
                              bg="#2C3E50", fg="white")
        self.title.pack()

        # Car image (center)
        self.car_label = tk.Label(self.mid, bg="#2C3E50")
        self.car_label.pack(pady=(8, 12))
        self._load_car_image("ComputerCode/CarPhoto.png", size=(260, 170))  # change path/size as you like

        # Output area (what the car says)
        # Uses a Label with wrap + a contrasting card-like frame
        card = tk.Frame(self.mid, bg="#34495E")
        card.pack(padx=28, pady=(0, 10), fill="x")

        self.output_var = tk.StringVar(value="Hello! I’m ready to talk")
        self.output = tk.Label(card, textvariable=self.output_var,
                               font=("Helvetica", 13), wraplength=380,
                               justify="center", bg="#34495E", fg="white",
                               padx=16, pady=12)
        self.output.pack(fill="x")

        # Status
        self.status_var = tk.StringVar(value="")
        self.status = tk.Label(self.mid, textvariable=self.status_var,
                               font=("Helvetica", 10, "italic"),
                               bg="#2C3E50", fg="lightgrey")
        self.status.pack()

        # Ask button (bottom)
        self.record_button = tk.Button(self.bottom, text="Ask me a question!",
                                       font=("Helvetica", 14, "bold"),
                                       relief="raised", bd=2, padx=12, pady=8,
                                       command=self.askQuestion)
        self.record_button.pack(pady=(8, 0))

        # Recording parameters
        self.fs = 44100
        self.seconds = 5

    # UI helper methods (for readability)
    def _load_car_image(self, path, size=(240, 150)):
        # Loads a car image from the specified path, resizes it, and displays it in the car_label widget. 
        # If loading fails, displays a placeholder text instead.
        """
        Loads a car image from the given file path, resizes it to the specified size, and sets it as the image
        for the car_label widget. If the image cannot be loaded, displays a placeholder text instead.

        Args:
            path (str): The file path to the car image.
            size (tuple, optional): The desired size (width, height) for the image. Defaults to (240, 150).

        Raises:
            Exception: If there is an error loading or processing the image, a placeholder is shown instead.
        """
        try:
            img = Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)
            self._car_photo = ImageTk.PhotoImage(img)  # must keep reference
            self.car_label.configure(image=self._car_photo)
        except Exception as e:
            self.car_label.configure(text="[Car image missing]",
                                     font=("Helvetica", 12, "italic"),
                                     fg="lightgrey")

    def set_output(self, text):
        # Updates the output variable with the provided text and refreshes the GUI to reflect the change.
        """
        Sets the output variable to the specified text and updates the GUI.

        Args:
            text (str): The text to display in the output variable.
        """
        self.output_var.set(text)
        self.master.update_idletasks()

    def set_status(self, text):
        # Updates the status display with the provided text.
        """
        Sets the status text in the GUI.

        Args:
            text (str): The status message to display.
        """
        self.status_var.set(text)
        self.master.update_idletasks()

    def _disable_button(self, disabled=True):
        # Disables or enables the record button in the GUI.
        """
        Enable or disable the record button in the GUI.

        Args:
            disabled (bool, optional): If True, disables the record button; if False, enables it. Defaults to True.

        Side Effects:
            Updates the button's state and refreshes the GUI to reflect the change.
        """
        self.record_button.config(state=("disabled" if disabled else "normal"))
        self.master.update_idletasks()
    
    def saySomething(self, text, wait=False):
        # This function generates speech audio from text and plays it, optionally waiting for playback to finish.
        """
        Converts the given text to speech using a specified speaker and plays the audio.

        Args:
            text (str): The text to be converted to speech.
            wait (bool, optional): If True, waits for the audio playback to finish before returning. Defaults to False.

        Returns:
            None
        """
        sample_rate = 48000
        speaker = 'en_11'
        put_accent=True
        put_yo=True

        audio = ttsmodel.apply_tts(text=text,
                                   speaker=speaker,
                                   sample_rate=sample_rate,
                                   put_accent=put_accent,
                                   put_yo=put_yo)
        sd.play(audio, sample_rate)

        if wait:
            sd.wait()   

    def askQuestion(self):
        """
        Generates a question, speaks it aloud, and initiates background listening for a user's response.

        This function performs the following steps:
        1. Generates a question and stores the expected answer.
        2. Updates the UI to display the question and disables the relevant button.
        3. Sets the status to indicate that the question is being spoken.
        4. Speaks the question aloud, waiting for completion.
        5. Starts a background thread to listen for and process the user's response, ensuring the UI remains responsive.
        """
        # Generate + speak question
        question, self.expected_answer = generate_question(QuestionType(random.randint(1, 4)))
        self.set_output(question)
        self._disable_button(True)
        self.set_status("Speaking...")
        self.saySomething(question, wait=True)

        # Start background thread so UI doesn't freeze while listening/transcribing
        threading.Thread(target=self._listen_and_process, daemon=True).start()

    def _listen_and_process(self):
        # This function listens for audio input, processes the answer, and re-enables the button afterwards.
        """
        Listens for audio input until silence is detected, processes the received answer,
        and ensures the associated button is re-enabled after processing.

        The method performs the following steps:
        1. Records audio input until silence is detected.
        2. Processes the recorded answer.
        3. Re-enables the button regardless of success or failure.
        """
        try:
            self.recordUntilSilence()
            self.processAnswer()
        finally:
            self._disable_button(False)

    def recordUntilSilence(self):
        # Records audio from the microphone until a period of silence is detected using voice activity detection (VAD).
        """
        Records audio input from the microphone until a specified duration of silence is detected, using the Silero voice activity detection (VAD) model.

        The function:
        - Initializes VAD and audio stream settings.
        - Starts recording when speech is detected above a threshold.
        - Continues recording until silence is detected for a specified duration.
        - Saves the recorded audio to a WAV file.
        - Updates the GUI status and output accordingly.

        Returns:
            None
        """
        # VAD settings
        CHANNELS = 1
        DTYPE = "int16"
        CHUNK_SAMPLES = 512                 # 32 ms @ 16 kHz (required by Silero)
        THRESH_START = 0.6
        THRESH_STOP  = 0.5
        SILENCE_MS   = 800

        self.set_status("🎤 Listening...")
        self.set_output(self.output_var.get())  # keep question visible

        # Use current default input if possible
        INPUT_DEVICE = sd.default.device[0] if isinstance(sd.default.device, (list, tuple)) else None

        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=DTYPE,
            blocksize=CHUNK_SAMPLES,
            device=INPUT_DEVICE,
            callback=audio_cb,
        )

        started = False
        silence_chunks_needed = int(np.ceil(SILENCE_MS / (1000 * CHUNK_SAMPLES / SAMPLE_RATE)))
        silence_run = 0
        collected = []

        stream.start()
        try:
            while True:
                chunk = q.get()
                if chunk.ndim == 2:
                    chunk = chunk[:, 0]

                collected.append(chunk)

                x = (torch.from_numpy(chunk.astype(np.float32)) / 32768.0).unsqueeze(0).to(device)
                with torch.no_grad():
                    prob = vadmodel(x, SAMPLE_RATE).item()

                if not started and prob >= THRESH_START:
                    started = True
                    silence_run = 0

                if started:
                    if prob < THRESH_STOP:
                        silence_run += 1
                    else:
                        silence_run = 0

                    if silence_run >= silence_chunks_needed:
                        break
        finally:
            stream.stop(); stream.close()

        # Save the recording
        audio = np.concatenate(collected, axis=0).astype(np.int16)
        out_path = os.path.join(OUT_DIR, "recording.wav")
        write_wav_int16(out_path, audio, SAMPLE_RATE)
        self.set_status("Thinking…")

    def processAnswer(self):
        # Processes the child's spoken answer, normalizes it, compares it to the expected answer, and provides feedback.
        """
        Transcribes the child's spoken answer from an audio file, normalizes both the transcribed and expected answers
        (by converting numbers to words, removing punctuation and spaces, and converting to lowercase), and compares them.
        Provides feedback indicating whether the answer is correct or incorrect, and sends a corresponding reaction.
        Steps:
        1. Transcribes the audio file "recording/recording.wav" to text.
        2. Normalizes the transcribed answer and the expected answer:
            - Converts numbers (1–9) to words.
            - Removes punctuation and spaces.
            - Converts to lowercase.
        3. Compares the normalized answers.
        4. If correct, provides positive feedback and sends a "RIGHT" reaction.
        5. If incorrect, provides corrective feedback with the correct answer and sends a "WRONG" reaction.
        6. Updates output and status accordingly.
        """
        # Transcribe
        result = whisperModel.transcribe("recording/recording.wav", fp16=False)
        childAnswer = result["text"]

        # Normalize both sides to words 1–9, lowercase, no spaces
        def num_to_word(match):
            n = int(match.group())
            return number_to_words(n)

        childAnswer = childAnswer.translate(str.maketrans('', '', string.punctuation)).lower()
        childAnswer = re.sub(r'\b\d+\b', num_to_word, childAnswer).replace(" ", "")

        expected = self.expected_answer.lower().replace(" ", "")

        if childAnswer == expected:
            self.saySomething("Correct!")
            send_reaction("RIGHT", token="monstercookiebrownie")
            
            
            self.set_output("Correct!")
            self.set_status("")
        else:
            msg = f"Incorrect. The correct answer is {self.expected_answer}. You said {childAnswer}."
            
            
            self.saySomething(msg)
            send_reaction("WRONG", token="monstercookiebrownie")
            self.set_output(msg)
            self.set_status("")

# Print the current default input/output device indices for sounddevice
print("Default input device:", sd.default.device)

# Print a list of all available audio devices (input/output) for reference
print("Available devices:")
print(sd.query_devices())

# Set the default input device to index 2 (output device remains unchanged)
sd.default.device = (2, None)  # (input_device_index, output_device_index)

# Run the Toy Car Buddy GUI application
root = tk.Tk()           # Create the main Tkinter window
app = CarGUIApp(root)    # Instantiate the CarGUIApp with the root window
root.mainloop()          # Start the Tkinter event loop (shows the GUI)