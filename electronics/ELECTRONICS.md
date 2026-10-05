
> **Previewing this file in VS Code:** the diagrams are Mermaid blocks. To render them in the built-in Markdown preview (`Ctrl+Shift+V`):
>
> - Install **Markdown Preview Mermaid Support** (`bierner.markdown-mermaid`)
> - Optional: install **Markdown Preview GitHub Styling** (`bierner.markdown-preview-github-styles`) for the GitHub look
> - Disable **Markdown Github Preview** (`lzm0x219.vscode-markdown-github`) and **Mermaid Preview** (`vstirbu.vscode-mermaid-preview`): they conflict with each other and leave diagrams empty or show "No diagram type detected"
> - Reload the window (`Developer: Reload Window`) after changing extensions
>
> On GitHub, the diagrams render without any setup.

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

## Data Connections

### LeRobot SO-101 (Follower Arm)

Servo bus (daisy chain, 3-pin TTL bus cable):

```
Servo 6 ──3pin── Servo 5 ──3pin── Servo 4 ──3pin── Servo 3 ──3pin── Servo 2 ──3pin── Servo 1 ──3pin── FE-URT-2
```

| From         | Port   | To      | Port   |
| ------------ | ------ | ------- | ------ |
| FE-URT-2     | Type-C | USB Hub | Type-A |
| Wrist Camera | USB    | USB Hub | Type-A |

```mermaid
flowchart LR
    S6[Servo 6] ---|3 pin| S5[Servo 5] ---|3 pin| S4[Servo 4] ---|3 pin| S3[Servo 3] ---|3 pin| S2[Servo 2] ---|3 pin| S1[Servo 1] ---|3 pin| URT[FE-URT-2]
    URT -->|Type-C → Type-A| HUB[USB Hub]
    WCAM[Wrist Camera] -->|USB → Type-A| HUB
```

### Operational Box

| From                     | Port   | To      | Port   |
| ------------------------ | ------ | ------- | ------ |
| Ambient Camera           | USB    | USB Hub | Type-A |
| Leader Arm Controll Board | Type-C | USB Hub | Type-A |

```mermaid
flowchart LR
    ACAM[Ambient Camera] -->|USB → Type-A| HUB[USB Hub]
    LEAD[Leader Arm Controll Board] -.->|Type-C → Type-A| HUB
```

> Leader Arm is outside of scope of this box and used only for training, so one type a port reserved for it on USB Hub, but it have its independed power supply(but with similar ground)

### Trash Drop Mechanism

| From                | Port   | To                  | Port   |
| ------------------- | ------ | ------------------- | ------ |
| ESP32-S3 Super Mini | Type-C | USB Hub             | Type-C |
| Servo 1             | 3 pin  | ESP32-S3 Super Mini | GPIO   |
| Servo 2             | 3 pin  | ESP32-S3 Super Mini | GPIO   |
| Servo 3             | 3 pin  | ESP32-S3 Super Mini | GPIO   |
| Servo 4             | 3 pin  | ESP32-S3 Super Mini | GPIO   |

```mermaid
flowchart LR
    ESP[ESP32-S3 Super Mini] -->|Type-C → Type-C| HUB[USB Hub]
    D1[Servo 1] -->|3 pin| ESP
    D2[Servo 2] -->|3 pin| ESP
    D3[Servo 3] -->|3 pin| ESP
    D4[Servo 4] -->|3 pin| ESP
```

### All Data Connections

```mermaid
flowchart LR
    HOST[Host PC]

    subgraph BOX[Operational Box]
        HUB[USB Hub]
        ACAM[Ambient Camera]
    end

    subgraph ARM[LeRobot SO-101 Follower Arm]
        S6[Servo 6] ---|3 pin| S5[Servo 5] ---|3 pin| S4[Servo 4] ---|3 pin| S3[Servo 3] ---|3 pin| S2[Servo 2] ---|3 pin| S1[Servo 1] ---|3 pin| URT[FE-URT-2]
        WCAM[Wrist Camera]
    end

    subgraph DROP[Trash Drop Mechanism]
        ESP[ESP32-S3 Super Mini]
        D1[Servo 1] -->|3 pin| ESP
        D2[Servo 2] -->|3 pin| ESP
        D3[Servo 3] -->|3 pin| ESP
        D4[Servo 4] -->|3 pin| ESP
    end

    LEAD[Leader Arm Controll Board]

    HUB -->|upstream| HOST
    URT -->|Type-C → Type-A| HUB
    WCAM -->|USB → Type-A| HUB
    ACAM -->|USB → Type-A| HUB
    ESP -->|Type-C → Type-C| HUB
    LEAD -.->|Type-C → Type-A, training only| HUB
```

## Power Demand

Values marked *est.* are typical values for this class of device (no datasheet available) and should be verified with a USB power meter.

### LeRobot SO-101 (Follower Arm)

| Item                     | Qty | Voltage | Current (each)                  | Power (each)              | Power (total)                 |
| ------------------------ | --- | ------- | ------------------------------- | ------------------------- | ----------------------------- |
| Feetech STS3215-C001 12V | 6   | 12V     | 0.18A no-load / 2.7A stall      | 2.2W no-load / 32.4W stall | 13W no-load / 194W all stalled |
| FE-URT-2 (CH343P logic)  | 1   | 5V USB  | ~0.03A *est.*                   | ~0.15W                    | ~0.15W                        |
| Wrist Camera (AIT SEMIC) | 1   | 5V USB  | ~0.15–0.25A *est.*, ≤0.5A (USB 2.0 limit) | ~0.75–1.25W    | ~0.75–1.25W                   |

> All 6 servos stalling at once is the worst case and won't happen in normal operation. A realistic peak during fast moves is around 3–5A at 12V.

### Operational Box

| Item                    | Qty | Voltage | Current (each)                     | Power (each) | Power (total) |
| ----------------------- | --- | ------- | ---------------------------------- | ------------ | ------------- |
| LED Lamp LN-12-6--50-4  | 2   | 12V     | 0.5A                               | 6W           | 12W (1A)      |
| Logitech C270           | 1   | 5V USB  | ~0.2A *est.*, ≤0.5A (USB 2.0 limit) | ~1W         | ~1W           |
| USB Hub BYL-2218TU      | 1   | 5V USB  | ~0.05A *est.* (own consumption)    | ~0.25W       | ~0.25W        |

### Trash Drop Mechanism

| Item                | Qty | Voltage           | Current (each)                              | Power (each)                 | Power (total)                  |
| ------------------- | --- | ----------------- | ------------------------------------------- | ---------------------------- | ------------------------------ |
| RDS3115             | 4   | 4.8–7.2V (TBD)    | 0.1A no-load / 2.5–3A stall (at 6V)         | 0.6W no-load / 15–18W stall (at 6V) | 2.4W no-load / 60–72W all stalled |
| ESP32-S3 Super Mini | 1   | 5V USB            | ~0.1A typ., up to ~0.35A with Wi-Fi TX *est.* | ~0.5W typ. / ~1.75W peak   | ~0.5–1.75W                     |

### Summary per Rail

| Rail          | Consumers                                     | Typical  | Peak (worst case)       |
| ------------- | --------------------------------------------- | -------- | ----------------------- |
| 12V           | 6x STS3215, 2x LED lamp                        | ~2.1A / 25W | 17.2A / 206W         |
| 5–7.2V (TBD)  | 4x RDS3115                                     | ~0.4A    | 10–12A                  |
| 5V USB (hub)  | FE-URT-2, Wrist Camera, C270, ESP32-S3, hub    | ~0.6A / 3W | ~1.4A / 7W            |

> The USB hub is bus-powered, so all 5V USB devices share the current of a single host port: 0.9A on USB 3.0 Type-A, 1.5–3A on Type-C. The Leader Arm board also plugs into this hub, but only for data.

## Power Supply

### LeRobot SO-101 (Follower Arm)

| Source     | Voltage | Consumer                                                   |
| ---------- | ------- | ---------------------------------------------------------- |
| USB Hub    | 5V      | FE-URT-2                                                   |
| USB Hub    | 5V      | Wrist Camera                                               |
| 12V supply | 12V     | Servo 1 → Servo 2 → Servo 3 → Servo 4 → Servo 5 → Servo 6 (via bus) |

```mermaid
flowchart LR
    HUB[USB Hub 5V] --> URT[FE-URT-2]
    HUB --> WCAM[Wrist Camera]
    PSU12[12V Supply] --> S1[Servo 1] --> S2[Servo 2] --> S3[Servo 3] --> S4[Servo 4] --> S5[Servo 5] --> S6[Servo 6]
```

### Operational Box

| Source     | Voltage | Consumer       |
| ---------- | ------- | -------------- |
| 12V supply | 12V     | Light Source   |
| USB Hub    | 5V      | Ambient Camera |

```mermaid
flowchart LR
    PSU12[12V Supply] --> LED[Light Source<br/>2x LED Lamp]
    HUB[USB Hub 5V] --> ACAM[Ambient Camera]
```

### Trash Drop Mechanism

| Source           | Voltage    | Consumer            |
| ---------------- | ---------- | ------------------- |
| USB Hub          | 5V         | ESP32-S3 Super Mini |
| TBD supply       | 5V or 7V   | Servo 1             |
| TBD supply       | 5V or 7V   | Servo 2             |
| TBD supply       | 5V or 7V   | Servo 3             |
| TBD supply       | 5V or 7V   | Servo 4             |

```mermaid
flowchart LR
    HUB[USB Hub 5V] --> ESP[ESP32-S3 Super Mini]
    PSUX[TBD Supply 5V or 7V] --> D1[Servo 1]
    PSUX --> D2[Servo 2]
    PSUX --> D3[Servo 3]
    PSUX --> D4[Servo 4]
```

### All Power Connections

```mermaid
flowchart LR
    HOST[Host PC USB port]
    PSU12[12V Supply]
    PSUX[TBD Supply 5V or 7V]
    HUB[USB Hub 5V, bus-powered]

    HOST -->|5V| HUB

    subgraph ARM[LeRobot SO-101 Follower Arm]
        URT[FE-URT-2]
        WCAM[Wrist Camera]
        S1[Servo 1] --> S2[Servo 2] --> S3[Servo 3] --> S4[Servo 4] --> S5[Servo 5] --> S6[Servo 6]
    end

    subgraph BOX[Operational Box]
        LED[Light Source<br/>2x LED Lamp]
        ACAM[Ambient Camera]
    end

    subgraph DROP[Trash Drop Mechanism]
        ESP[ESP32-S3 Super Mini]
        D1[Servo 1]
        D2[Servo 2]
        D3[Servo 3]
        D4[Servo 4]
    end

    HUB -->|5V| URT
    HUB -->|5V| WCAM
    HUB -->|5V| ACAM
    HUB -->|5V| ESP
    PSU12 -->|12V| S1
    PSU12 -->|12V| LED
    PSUX --> D1
    PSUX --> D2
    PSUX --> D3
    PSUX --> D4
```

