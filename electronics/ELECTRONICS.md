
## Components

### LeRobot SO-101 (Follower Arm)

- Servos: 6x Feetech STS3215-C001 12V Servo
- Wrist camera: generic UVC camera on an Alpha Imaging Tech. (AIT) chip, reported as "SEMIC Camera"
- Controll Board: Feetech FE-URT-2 Servo Debug Programmer, USB Type-C to TTL/RS485 Bus Adapter with CH343P

### Operational Box

- Ambient camera: Logitech Webcam C270 (USB `046d:0825`, 720p UVC)
- Light Source: 2x Linear LED Lamp OEM 12V LN-12-6--50-4 6W 50cm 4500K
- USB Hub: USB Hub Dynamode USB-C/A 8-in-1 1xUSB-C + 1xUSB 3.0 + 3xUSB 2.0 + 3.5mm audio + SD/TF silver (BYL-2218TU)

### Trash Drop Mechanism

- Servos: 4x RDS3115 7.2V 180 deg
- Servo controller: ESP32-S3 Super Mini 

## Connections 

### LeRobot SO-101 (Follower Arm)

Servo 6 [3 pin]->[3 pin] Servo 5 [3 pin]->[3 pin] Servo 4 [3 pin]->[3 pin] Servo 3 [3 pin]->[3 pin] Servo 2 [3 pin]->[3 pin] Servo 1 [3 pin]->[3 pin] FE-URT-2

FE-URT-2 [type-c]->[type-a] USB HUB

Wrist Camera ->[type-a] USB HUB

### Operational Box

Ambient Camera ->[type-a] USB HUB

Leader Arm Controll Board [type-c]->[ttype-a] USB HUB

> Leader Arm is outside of scope of this box and used only for training, so one type a port reserved for it on USB Hub, but it have its independed power supply(but with similar ground)

### Trash Drop Mechanism

ESP32-S3 Super Mini [type-c]->[type-c] USB HUB

Servo 1 ->[3 pin] ESP32-S2 Super Mini

Servo 2 ->[3 pin] ESP32-S2 Super Mini

Servo 3 ->[3 pin] ESP32-S2 Super Mini

Servo 4 ->[3 pin] ESP32-S2 Super Mini

## Power Demand

### LeRobot SO-101 (Follower Arm)

...

### Operational Box

...

### Trash Drop Mechanism

...

## Power Supply

### LeRobot SO-101 (Follower Arm)

5V USB HUB -> FE-URT-2

5V USB HUB -> Wrist Camera

12V -> Servo 1 -> Servo 2 -> Servo 3 -> Servo 4 -> Servo 5 -> Servo 6

### Operational Box

12V -> Light Source

5V USB HUB -> Ambient Camera

### Trash Drop Mechanism

5V USB HUB -> ESP32-S2 Super Mini

TBD(5V or 7V) -> Servo 1

TBD(5V or 7V) -> Servo 2

TBD(5V or 7V) -> Servo 3

TBD(5V or 7V) -> Servo 4

