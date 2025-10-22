<p align="center">
  <img src="ComputerCode/CarPhoto.png" alt="Toy Car System" width="250"/>
</p>

![Blink](https://github.com/user-attachments/assets/a9a502ca-a341-44fd-9728-311ebfc2d0ee)
![LeftRight](https://github.com/user-attachments/assets/b6e67a7f-943b-4e74-b97c-1c128f079064)
![Wrong-x](https://github.com/user-attachments/assets/a0263805-2692-4a16-84e9-ec2f0646255d)
![Wrong-Shake](https://github.com/user-attachments/assets/740aa25b-d23e-4a53-b793-258d24b72c72)
![Right-star](https://github.com/user-attachments/assets/d548d23c-4350-4c92-b9f6-75a04950c15f)
![Right-slotmachine](https://github.com/user-attachments/assets/5fc95818-7167-4a89-9181-a3b5facc5ae2)

# Toy Car System
An interactive educational toy car that uses **digit recognition** to assess the **math ability of young children**.  
This project forms part of my final-year **Mechatronic Engineering Skripsie** at Stellenbosch University.

PS: The above six gifs are the six reactions the car performs on the OLED - animated by me!

---

## Project Overview

The Toy Car System combines **hardware** and **speech recognition software** to create an engaging learning experience for children.  
When a child answers a spoken math question, the car responds with **lights, movement, the OLED display and sound** based on the correctness of the answer.

---
## Project Demonstration


https://github.com/user-attachments/assets/25eb206e-31ae-4bf9-9bd9-e5be2d422ba7


---

## File Description

| File | Description |
|------------|--------------|
| **CarCode** | The file that contains all files contained, and code that is run on the Raspberry Pi.|
| **ComputerCode** | Contains the code and files that allow the GUI to be run on a computer.|

---

## How it works

The Toy Car System consists of two main components that work together over a local network:

1. **The Raspberry Pi (Toy Car)**
2. **The Computer (GUI)**

Each component performs a distinct role, and communication between them ensures the toy responds correctly to the child’s spoken answers.

---

### Raspberry Pi (Toy Car)

The Raspberry Pi Zero 2 W is mounted inside the toy car and handles all **mechanical and interactive functions**.  
It connects to Wi-Fi and continuously waits for commands from the computer.

**Main responsibilities:**
- Drives the **DC motors** (forward, reverse, turn).
- Controls the **servo motor** for steering.
- Updates the **OLED display** to show feedback (the OLED acts as the eyes of the car).
- Handles **connection management** — if the Pi disconnects from the network, the service automatically attempts to reconnect after 2 seconds.

---

### Computer (GUI and Speech Recognition)

The GUI runs on a laptop or desktop computer and provides the main **user interface**.  
It allows a teacher or parent to start math sessions and interact with the toy.

**Main responsibilities:**
- Records the child’s **spoken response** to a math question.
- Runs the **speech recognition pipeline** to determine the digit that was spoken.
- Compares the recognised digit to the correct answer.
- Sends a simple **command message** to the Raspberry Pi to indicate whether the answer was correct or incorrect.

---

### Communication Between Pi and Computer

Communication happens via a lightweight **network socket connection** (TCP).  
Both devices connect to the same Wi-Fi network.

- The **Pi acts as a server**, continuously listening for incoming messages.  
- The **Computer acts as a client**, sending a short command string such as:
    - `RIGHT` → The car reacts with one of its `right` reactions.  
    - `WRONG` → The car reacts with one of its `wrong` reactions.  
    - `IDLE` → The car remains stationary, LEDs are off, and the OLED shows a neutral face.  
    - `PING` → Used to check connectivity; the car responds with `PONG` to confirm it is online.

This simple protocol ensures low latency and reliability, even on a lightweight Raspberry Pi.

---

### Overall Flow

1. The GUI asks a math question (e.g. “What is 2 + 3?”).  
2. The child speaks their answer.  
3. The computer records and processes the speech to determine the digit (“5”).  
4. The system compares it with the correct answer.  
5. A message is sent to the Raspberry Pi via the socket connection.  
6. The Pi drives motors, lights, and sounds to display the result.  
7. The child can initiate another question to be asked
and this repeats


