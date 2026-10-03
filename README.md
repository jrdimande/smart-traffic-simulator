# Smart Traffic Simulator

An academic project that combines a traffic intersection simulator with Machine Learning to implement an adaptive traffic light system, and compares it with a conventional fixed-time controller.

## Overview

Smart Traffic Simulator is a two-dimensional simulation of a four-way intersection, built with Pygame. It compares two traffic-light control approaches under identical traffic conditions:

1. A fixed-time controller with a constant green duration.
2. An adaptive controller in which a Machine Learning model predicts the green-light duration.

The objective is to investigate whether adaptive signal timing can reduce vehicle waiting time and improve traffic flow compared with a fixed-time approach.

## Problem

A fixed-time traffic light assigns the same green duration to each approach regardless of current demand. When demand is uneven, green time may be spent on an approach with few or no vehicles while vehicles accumulate on the other. Adaptive control adjusts timing according to observed conditions, which may reduce waiting time.

## Proposed Solution

The adaptive controller measures the current traffic state of each axis (north/south and east/west), queries a trained model for the green duration, and selects the next phase.

```text
Traffic Conditions (vehicles, accumulated waiting, opposite vehicles)
        ↓
Machine Learning Model
        ↓
Predicted Green Time (per axis)
        ↓
Phase Selection (rule-based) and Traffic Light Control
        ↓
Updated Traffic Conditions
```

The model predicts the duration only. The choice of which axis receives the green phase is made by a rule-based procedure described in [Machine Learning Control](#machine-learning-control).

## System Architecture

| Component | Role |
|---|---|
| `main.py` / `simulator.py` | Simulation, rendering, vehicles, traffic lights, controllers, benchmark and results screen. [ split of responsibilities between the two files] |
| `train_model.py` | Trains the model and saves it.|
| `src/model/traffic_model.joblib` | Serialized trained model, loaded with `joblib`. |
| `data/traffic_data.csv` | Training dataset|

## Machine Learning Model

- **Algorithm:** [`train_model.py`]
- **Input features (three, in this order):**
  1. `vehicles`: number of vehicles currently in the axis being evaluated.
  2. `waiting`: accumulated waiting indicator of that axis (seconds without green, see below).
  3. `opposite`: number of vehicles in the opposite axis.
- **Output:** a single numeric value interpreted as green duration in seconds. The simulator clamps it to the range 5 to 45 s and rounds it to an integer.
- **Training process:** 
- **Dataset:** [state explicitly whether it is synthetic]
- **Model storage:** the model is loaded with `joblib`. If the file is missing, or if prediction raises an exception, the simulator falls back to a constant prediction of 20 s.

## Traffic Simulator

The simulator renders a single intersection of two roads, with two lanes per direction, in a full-screen Pygame window.

- **Directions:** vehicles enter from north (N), south (S), east (E) or west (W). Vehicles move straight through the intersection; turning is not modelled.
- **Vehicle generation:** each vehicle is assigned a direction, one of two lanes, and a speed drawn uniformly between 70 and 115 pixels per second. The interval between arrivals is drawn uniformly between 0.65 and 1.60 s and divided by a density factor.
- **Traffic distribution:** three scenarios are available: 80% of arrivals on the N/S axis, 80% on the E/W axis, or balanced (equal probability per direction).
- **Density:** a multiplier between 0.25x and 3.0x, adjustable in steps of 0.25.
- **Vehicle movement:** a vehicle advances while its axis has green. It stops at the stop line when its axis has red, and stops when the vehicle ahead in the same direction and lane is closer than 82 pixels.
- **Waiting time:** a vehicle accumulates waiting time at each step in which its displacement is below 0.5 pixels. A vehicle is counted as evacuated once it passes a point 80 pixels beyond the edge of the intersection.
- **Phases:** the light has two phases, N/S green or E/W green. A yellow phase is not simulated.

The side panel displays, for each axis, the vehicle count, queue size (vehicles with accumulated waiting above 0.2 s), time without green and predicted green time, together with the current controller state and performance indicators (evacuated vehicles, flow per minute, recent average waiting time, and a comparison of recent averages for ML and fixed vehicles).

## Traffic Light Control

### Fixed-Time Control

Each phase lasts 20 seconds, alternating between N/S and E/W regardless of traffic.

### Machine Learning Control

When a phase ends, the controller counts vehicles per axis and queries the model once per axis, using the inputs `(vehicles, waiting, opposite vehicles)`. The `waiting` value of an axis increases while the other axis has green and that axis has vehicles, and decreases at 1.2 times real time while the axis has green. The next phase is then selected as follows:

1. If one axis is empty and the other has vehicles, the occupied axis receives green for `max(5, predicted time)`.
2. If both axes are empty, the phase alternates for 6 s.
3. Otherwise, a score is computed per axis: `1.5 * vehicles + 1.8 * waiting + queue`.
   - If an axis has waiting of at least 12 s and more than the other axis, it receives green for the predicted time clamped to 8 to 30 s.
   - Otherwise, the axis with the higher score receives green for the predicted time clamped to 6 to 35 s.

## Evaluation

Pressing `B` starts a benchmark based on the current density and traffic distribution:

1. A random seed generates one list of vehicle arrivals covering 60 simulated seconds.
2. The fixed-time controller is run on this scenario for 60 s.
3. The ML controller is run on exactly the same scenario for 60 s.
4. A results screen compares both runs.

| Metric | Definition |
|---|---|
| Vehicles generated | Vehicles spawned during the run |
| Evacuated | Vehicles that passed the intersection |
| Remaining | Generated minus evacuated |
| Average wait | Mean waiting time of evacuated vehicles only |
| Flow | Evacuated vehicles per minute |
| Difference | Percentage change of ML relative to fixed-time, for average wait and for flow |

Each benchmark is a single 60-second run with a random seed, so results vary between executions. No numerical results are reported in this document.

## Technologies

- Python
- Pygame (rendering and event handling)
- joblib (model loading)
- [library used to train and run the model, and the full contents of `requirements.txt`]

## Project Structure

```text
smart-traffic-simulator/
│
├── src/
│   └── model/
│       └── traffic_model.joblib
│
├── data/
│   └── traffic_data.csv
│
├── main.py
├── simulator.py
├── train_model.py
├── requirements.txt
└── README.md
```

## Installation

```bash
git clone <repository-url>
cd smart-traffic-simulator

python -m venv venv

# Linux / macOS
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

## Usage

1. Train the model:

```bash
python train_model.py
```

2. Run the simulator:

```bash
python main.py
```

[ entry-point file and training command.]

## Simulator Controls

| Key | Function |
|---|---|
| `1` | Traffic scenario: 80% N/S |
| `2` | Traffic scenario: 80% E/W |
| `3` | Traffic scenario: balanced |
| `+` / `=` | Increase density by 0.25 (maximum 3.0) |
| `-` | Decrease density by 0.25 (minimum 0.25) |
| `F` | Toggle between ML control and fixed-time control |
| `B` | Run the 60-second benchmark (fixed-time, then ML) |
| `R` | Restart the simulation (density and distribution return to defaults) |
| `Space` | Pause or resume |
| `Esc` | Quit |

On the benchmark results screen, `Enter` returns to the simulation (keeping the current density and distribution) and `Esc` quits. During a benchmark stage, `Esc` ends that stage early.

The graphical interface is currently in Portuguese.

## Dataset

[ purpose, columns, number of rows and origin of `data/traffic_data.csv`. State explicitly if the data is synthetic.]
## Limitations

- Simulation of a single isolated intersection; no real-world deployment or physical sensors.
- Simplified traffic model: straight movement only, two lanes per direction, no turns, pedestrians, yellow phase or vehicle types.
- The model predicts only green duration; phase selection relies on hand-defined rules and thresholds.
- If the model file is not found, the controller silently falls back to a constant 20 s prediction.
- The benchmark consists of a single randomly seeded 60-second scenario per run, so it does not provide statistical conclusions. Average wait considers only vehicles that completed the crossing.
- [limitations regarding the training data]

## Future Work

The following are possible directions, not existing features:

- Training with real-world traffic data
- Integration with physical traffic sensors
- More complex intersections, turning movements and additional traffic conditions
- Repeated benchmarks over multiple seeds with statistical analysis
- More advanced Machine Learning techniques, including Reinforcement Learning
- Hardware implementation

