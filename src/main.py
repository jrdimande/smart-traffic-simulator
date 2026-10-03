import os
import sys
import random
import pygame
import joblib

from collections import deque

# Simulation settings
FPS = 60
BENCHMARK_DURATION = 60.0

# Number of recent samples used for the average wait metrics
RECENT_WAIT_WINDOW = 40
MODE_WAIT_WINDOW = 150

# Colors
BG = (255, 255, 255)

ROAD = (75, 79, 84)
ROAD_EDGE = (35, 38, 42)
LANE = (205, 205, 205)

BLACK = (25, 25, 25)
DARK = (55, 55, 55)
WHITE = (255, 255, 255)

GREEN = (30, 190, 75)
RED = (220, 50, 50)
YELLOW = (245, 185, 35)

LIGHT_GREEN = (225, 250, 232)
LIGHT_BLUE = (230, 240, 255)
LIGHT_RED = (255, 232, 232)
LIGHT_GRAY = (242, 242, 242)

CAR_COLORS = [
    (40, 100, 200),
    (220, 70, 70),
    (40, 170, 100),
    (240, 150, 40),
    (130, 70, 190),
    (30, 160, 170),
    (220, 100, 160),
]


def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


class SpawnEvent:
    # One scheduled vehicle arrival, used to replay the same scenario twice

    def __init__(
            self,
            time,
            direction,
            lane,
            speed,
            color_index
    ):
        self.time = time
        self.direction = direction
        self.lane = lane
        self.speed = speed
        self.color_index = color_index


def generate_scenario(
        seed,
        duration,
        density,
        distribution
):
    # Build a reproducible list of arrivals from a seed
    rng = random.Random(seed)
    events = []
    current_time = 0.0

    while current_time < duration:
        if distribution == "NS":
            direction = rng.choices(
                ["N", "S", "E", "W"],
                weights=[40, 40, 10, 10],
                k=1
            )[0]
        elif distribution == "EW":
            direction = rng.choices(
                ["N", "S", "E", "W"],
                weights=[10, 10, 40, 40],
                k=1
            )[0]
        else:
            direction = rng.choice(
                ["N", "S", "E", "W"]
            )

        lane = rng.choice([0, 1])
        speed = rng.uniform(70, 115)
        color_index = rng.randrange(len(CAR_COLORS))

        events.append(
            SpawnEvent(
                current_time,
                direction,
                lane,
                speed,
                color_index
            )
        )

        interval = rng.uniform(0.65, 1.60)
        interval /= max(0.25, density)
        current_time += interval

    return events


class Car:

    def __init__(
            self,
            sim,
            direction,
            lane,
            speed=None,
            color_index=None
    ):
        self.sim = sim
        self.direction = direction
        self.lane = lane
        self.spawn_time = sim.sim_time

        if speed is None:
            self.speed = random.uniform(70, 115)
        else:
            self.speed = speed

        self.width = 32
        self.height = 58

        if color_index is None:
            self.color = random.choice(CAR_COLORS)
        else:
            self.color = CAR_COLORS[color_index % len(CAR_COLORS)]

        self.passed = False
        self.waiting_time = 0.0
        self.total_system_time = 0.0
        self.counted_as_active = False

        # Remember which controller was active when the car was created
        self.control_mode = (
            "FIXO" if sim.fixed_time_mode else "ML"
        )

        cx = sim.CENTER_X
        cy = sim.CENTER_Y
        offset = sim.ROAD_W / 4

        # Starting position outside the screen, depending on direction
        if direction == "N":
            self.x = cx - offset + lane * 36
            self.y = -90
        elif direction == "S":
            self.x = cx + offset - lane * 36
            self.y = sim.HEIGHT + 90
        elif direction == "E":
            self.x = sim.WIDTH + 90
            self.y = cy - offset + lane * 36
        else:
            self.x = -90
            self.y = cy + offset - lane * 36

    def get_rect(self):
        if self.direction in ("N", "S"):
            return pygame.Rect(
                int(self.x - self.width / 2),
                int(self.y - self.height / 2),
                self.width,
                self.height
            )
        return pygame.Rect(
            int(self.x - self.height / 2),
            int(self.y - self.width / 2),
            self.height,
            self.width
        )

    def minimum_car_distance(self):
        return 82

    def car_ahead(self):
        # Find the closest car in front, in the same direction and lane
        closest = None
        closest_distance = float("inf")

        for other in self.sim.cars:
            if other is self:
                continue
            if other.direction != self.direction:
                continue
            if other.lane != self.lane:
                continue

            if self.direction == "N":
                if other.y > self.y:
                    distance = other.y - self.y
                else:
                    continue
            elif self.direction == "S":
                if other.y < self.y:
                    distance = self.y - other.y
                else:
                    continue
            elif self.direction == "E":
                if other.x < self.x:
                    distance = self.x - other.x
                else:
                    continue
            else:
                if other.x > self.x:
                    distance = other.x - self.x
                else:
                    continue

            if distance < closest_distance:
                closest_distance = distance
                closest = other

        return closest, closest_distance

    def stop_position(self):
        distance = self.sim.ROAD_W / 2 + 48
        if self.direction == "N":
            return self.sim.CENTER_Y - distance
        if self.direction == "S":
            return self.sim.CENTER_Y + distance
        if self.direction == "E":
            return self.sim.CENTER_X + distance
        return self.sim.CENTER_X - distance

    def has_green(self):
        if self.direction in ("N", "S"):
            return self.sim.phase == "NS"
        return self.sim.phase == "EW"

    def update(self, dt):
        old_x = self.x
        old_y = self.y

        front_car, front_distance = self.car_ahead()
        moving_allowed = True

        # Keep a safe distance from the car in front
        if front_car is not None and front_distance < self.minimum_car_distance():
            moving_allowed = False

        if self.has_green():
            if moving_allowed:
                if self.direction == "N":
                    self.y += self.speed * dt
                elif self.direction == "S":
                    self.y -= self.speed * dt
                elif self.direction == "E":
                    self.x -= self.speed * dt
                else:
                    self.x += self.speed * dt
        else:
            # Red light: move up to the stop line and wait there
            stop = self.stop_position()
            if self.direction == "N":
                if self.y + self.height / 2 < stop:
                    if moving_allowed:
                        self.y += self.speed * dt
                    if self.y + self.height / 2 > stop:
                        self.y = stop - self.height / 2
                else:
                    moving_allowed = False
            elif self.direction == "S":
                if self.y - self.height / 2 > stop:
                    if moving_allowed:
                        self.y -= self.speed * dt
                    if self.y - self.height / 2 < stop:
                        self.y = stop + self.height / 2
                else:
                    moving_allowed = False
            elif self.direction == "E":
                if self.x - self.height / 2 > stop:
                    if moving_allowed:
                        self.x -= self.speed * dt
                    if self.x - self.height / 2 < stop:
                        self.x = stop + self.height / 2
                else:
                    moving_allowed = False
            else:
                if self.x + self.height / 2 < stop:
                    if moving_allowed:
                        self.x += self.speed * dt
                    if self.x + self.height / 2 > stop:
                        self.x = stop - self.height / 2
                else:
                    moving_allowed = False

        # A car that barely moved during this step counts as waiting
        movement = abs(self.x - old_x) + abs(self.y - old_y)
        if movement < 0.5:
            self.waiting_time += dt
            self.sim.total_wait_time += dt

        self.check_passed()

    def check_passed(self):
        if self.passed:
            return

        cx = self.sim.CENTER_X
        cy = self.sim.CENTER_Y
        passed = False

        # A car has passed once it is clear of the intersection
        if self.direction == "N":
            passed = self.y > cy + self.sim.ROAD_W / 2 + 80
        elif self.direction == "S":
            passed = self.y < cy - self.sim.ROAD_W / 2 - 80
        elif self.direction == "E":
            passed = self.x < cx - self.sim.ROAD_W / 2 - 80
        else:
            passed = self.x > cx + self.sim.ROAD_W / 2 + 80

        if passed:
            self.passed = True
            self.sim.total_passed += 1
            system_duration = self.sim.sim_time - self.spawn_time
            self.total_system_time = system_duration

            self.sim.completed_wait_times.append(self.waiting_time)
            self.sim.completed_system_times.append(system_duration)

            if self.waiting_time > self.sim.max_wait_time_recorded:
                self.sim.max_wait_time_recorded = self.waiting_time

            if self.control_mode == "ML":
                self.sim.ml_wait_times.append(self.waiting_time)
            else:
                self.sim.fixed_wait_times.append(self.waiting_time)

            if self.sim.benchmark_active:
                self.sim.benchmark_completed += 1
                self.sim.benchmark_wait_sum += self.waiting_time
                self.sim.benchmark_system_time_sum += system_duration
                if self.waiting_time > self.sim.benchmark_max_wait:
                    self.sim.benchmark_max_wait = self.waiting_time

    def draw(self, screen):
        rect = self.get_rect()
        pygame.draw.rect(screen, self.color, rect, border_radius=8)

        if self.direction in ("N", "S"):
            window = pygame.Rect(rect.x + 5, rect.y + 8, rect.width - 10, 16)
        else:
            window = pygame.Rect(rect.x + 8, rect.y + 5, 16, rect.height - 10)

        pygame.draw.rect(screen, (60, 100, 150), window, border_radius=4)
        pygame.draw.rect(screen, WHITE, rect, 2, border_radius=8)


class TrafficLight:

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.width = 82
        self.height = 220

    def draw(self, screen, state):
        rect = pygame.Rect(
            self.x - self.width // 2,
            self.y - self.height // 2,
            self.width,
            self.height
        )
        pygame.draw.rect(screen, (30, 30, 30), rect, border_radius=15)
        pygame.draw.rect(screen, (90, 90, 90), rect, 3, border_radius=15)

        radius = 27
        positions = [
            (self.x, self.y - 65),
            (self.x, self.y),
            (self.x, self.y + 65)
        ]

        pygame.draw.circle(
            screen, RED if state == "RED" else (75, 35, 35), positions[0], radius
        )
        pygame.draw.circle(
            screen, YELLOW if state == "YELLOW" else (80, 70, 30), positions[1], radius
        )
        pygame.draw.circle(
            screen, GREEN if state == "GREEN" else (30, 75, 40), positions[2], radius
        )


class Simulation:

    def __init__(self, screen, fixed_time_mode=False):
        self.screen = screen
        self.WIDTH, self.HEIGHT = screen.get_size()
        self.SIM_WIDTH = int(self.WIDTH * 0.70)
        self.CENTER_X = self.SIM_WIDTH * 0.50
        self.CENTER_Y = self.HEIGHT * 0.53
        self.ROAD_W = int(self.HEIGHT * 0.32)

        # Load the trained model if it exists
        model_path = "models/traffic_model.joblib"
        if not os.path.exists(model_path):
            self.model = None
        else:
            self.model = joblib.load(model_path)

        self.cars = []
        self.running = True
        self.paused = False
        self.fixed_time_mode = fixed_time_mode
        self.fixed_green_time = 20

        self.phase = "NS"
        self.phase_remaining = 1.0
        self.phase_duration = 1.0

        self.manual_density = 1.0
        self.spawn_timer = 0
        self.traffic_distribution = "NS"

        self.ns_vehicles = 0
        self.ew_vehicles = 0
        self.ns_queue = 0
        self.ew_queue = 0
        self.wait_ns = 0.0
        self.wait_ew = 0.0

        self.ns_green_time = 20
        self.ew_green_time = 20
        self.ai_decision = "N/S"
        self.ai_reason = "A analisar..."

        self.total_generated = 0
        self.total_passed = 0
        self.total_wait_time = 0
        self.max_wait_time_recorded = 0.0

        self.completed_wait_times = deque(maxlen=RECENT_WAIT_WINDOW)
        self.completed_system_times = deque(maxlen=RECENT_WAIT_WINDOW)
        self.ml_wait_times = deque(maxlen=MODE_WAIT_WINDOW)
        self.fixed_wait_times = deque(maxlen=MODE_WAIT_WINDOW)
        self.sim_time = 0.0

        self.near_threshold = min(self.SIM_WIDTH, self.HEIGHT) * 0.35
        self.ns_near = 0
        self.ew_near = 0

        # Benchmark state
        self.replay_events = None
        self.replay_index = 0
        self.benchmark_active = False
        self.benchmark_wait_sum = 0
        self.benchmark_system_time_sum = 0
        self.benchmark_completed = 0
        self.benchmark_max_wait = 0.0

        self.debug_decisions = []
        self.model_predictions_log = []
        self.model_inputs_log = []

        self.light_ns = TrafficLight(
            int(self.CENTER_X - self.ROAD_W * 0.85),
            int(self.CENTER_Y - self.ROAD_W * 0.72)
        )
        self.light_ew = TrafficLight(
            int(self.CENTER_X + self.ROAD_W * 0.85),
            int(self.CENTER_Y + self.ROAD_W * 0.72)
        )

        self.make_ai_decision()

    def counts(self):
        # Vehicles currently in the simulation, per axis
        ns = 0
        ew = 0
        for car in self.cars:
            if car.passed:
                continue
            if car.direction in ("N", "S"):
                ns += 1
            else:
                ew += 1
        return ns, ew

    def queue_counts(self):
        # Vehicles that have been waiting for more than 0.2 s, per axis
        ns = 0
        ew = 0
        for car in self.cars:
            if car.passed:
                continue
            if car.waiting_time <= 0.2:
                continue
            if car.direction in ("N", "S"):
                ns += 1
            else:
                ew += 1
        return ns, ew

    def near_counts(self):
        # Vehicles close to the intersection, per axis
        ns = 0
        ew = 0
        for car in self.cars:
            if car.passed:
                continue
            if car.direction in ("N", "S"):
                if abs(car.y - self.CENTER_Y) <= self.near_threshold:
                    ns += 1
            else:
                if abs(car.x - self.CENTER_X) <= self.near_threshold:
                    ew += 1
        return ns, ew

    def prediction(self, vehicles, waiting, opposite):
        self.model_inputs_log.append({
            "time": self.sim_time,
            "vehicles": vehicles,
            "waiting": waiting,
            "opposite": opposite
        })

        # Fall back to 20 s if there is no model or prediction fails
        if self.model is None:
            pred = 20.0
        else:
            try:
                pred = float(self.model.predict([[vehicles, waiting, opposite]])[0])
            except Exception:
                pred = 20.0

        self.model_predictions_log.append(pred)
        return int(round(clamp(pred, 5, 45)))

    def make_ai_decision(self):
        ns, ew = self.counts()
        self.ns_vehicles = ns
        self.ew_vehicles = ew
        self.ns_queue, self.ew_queue = self.queue_counts()

        # Fixed-time mode: alternate phases with a constant duration
        if self.fixed_time_mode:
            self.ns_green_time = self.fixed_green_time
            self.ew_green_time = self.fixed_green_time

            if self.phase == "NS":
                self.phase = "EW"
                self.ai_decision = "L/O"
            else:
                self.phase = "NS"
                self.ai_decision = "N/S"

            self.phase_remaining = float(self.fixed_green_time)
            self.phase_duration = float(self.fixed_green_time)
            self.ai_reason = f"FIXO: {self.fixed_green_time}s"
            return

        # ML mode: the model predicts the green time for each axis
        self.ns_green_time = self.prediction(ns, self.wait_ns, ew)
        self.ew_green_time = self.prediction(ew, self.wait_ew, ns)

        if ns == 0 and ew > 0:
            # North/south is empty, give green to east/west
            self.phase = "EW"
            self.ai_decision = "L/O"
            chosen_duration = max(5, self.ew_green_time)
            self.ai_reason = "ML: Direção N/S vazia"
        elif ew == 0 and ns > 0:
            # East/west is empty, give green to north/south
            self.phase = "NS"
            self.ai_decision = "N/S"
            chosen_duration = max(5, self.ns_green_time)
            self.ai_reason = "ML: Direção L/O vazia"
        elif ns == 0 and ew == 0:
            # No cars at all, switch quickly
            if self.phase == "NS":
                self.phase = "EW"
                self.ai_decision = "L/O"
            else:
                self.phase = "NS"
                self.ai_decision = "N/S"
            chosen_duration = 6.0
            self.ai_reason = "ML: Vias limpas (giro rápido)"
        else:
            # Score each axis by vehicles, accumulated wait and queue
            WAIT_WEIGHT = 1.8
            score_ns = (ns * 1.5) + (self.wait_ns * WAIT_WEIGHT) + self.ns_queue
            score_ew = (ew * 1.5) + (self.wait_ew * WAIT_WEIGHT) + self.ew_queue

            # If one axis has waited too long, give it green regardless of score
            MAX_WAIT_FORCE = 12.0
            if self.wait_ns >= MAX_WAIT_FORCE and self.wait_ns > self.wait_ew:
                self.phase = "NS"
                self.ai_decision = "N/S"
                chosen_duration = clamp(self.ns_green_time, 8, 30)
                self.ai_reason = f"Justiça N/S (Espera: {self.wait_ns:.1f}s)"
            elif self.wait_ew >= MAX_WAIT_FORCE and self.wait_ew > self.wait_ns:
                self.phase = "EW"
                self.ai_decision = "L/O"
                chosen_duration = clamp(self.ew_green_time, 8, 30)
                self.ai_reason = f"Justiça L/O (Espera: {self.wait_ew:.1f}s)"
            else:
                if score_ns > score_ew:
                    self.phase = "NS"
                    self.ai_decision = "N/S"
                    chosen_duration = clamp(self.ns_green_time, 6, 35)
                    self.ai_reason = f"ML Dinâmico: Prioridade N/S"
                else:
                    self.phase = "EW"
                    self.ai_decision = "L/O"
                    chosen_duration = clamp(self.ew_green_time, 6, 35)
                    self.ai_reason = f"ML Dinâmico: Prioridade L/O"

        self.phase_remaining = float(chosen_duration)
        self.phase_duration = float(chosen_duration)

    def update_waiting(self, dt):
        # The axis without green accumulates wait, the other one recovers
        if self.phase == "NS":
            if self.ew_vehicles > 0:
                self.wait_ew += dt
            self.wait_ns = max(0.0, self.wait_ns - dt * 1.2)
        else:
            if self.ns_vehicles > 0:
                self.wait_ns += dt
            self.wait_ew = max(0.0, self.wait_ew - dt * 1.2)

    def spawn_car(self):
        if self.traffic_distribution == "NS":
            direction = random.choices(["N", "S", "E", "W"], weights=[40, 40, 10, 10], k=1)[0]
        elif self.traffic_distribution == "EW":
            direction = random.choices(["N", "S", "E", "W"], weights=[10, 10, 40, 40], k=1)[0]
        else:
            direction = random.choice(["N", "S", "E", "W"])

        lane = random.choice([0, 1])
        self.cars.append(Car(self, direction, lane))
        self.total_generated += 1

    def spawn_replay_events(self):
        # Spawn cars from the pre-generated benchmark scenario
        if self.replay_events is None:
            return
        while (
                self.replay_index < len(self.replay_events)
                and self.replay_events[self.replay_index].time <= self.sim_time
        ):
            event = self.replay_events[self.replay_index]
            self.cars.append(
                Car(
                    self,
                    event.direction,
                    event.lane,
                    speed=event.speed,
                    color_index=event.color_index
                )
            )
            self.total_generated += 1
            self.replay_index += 1

    def update(self, dt):
        if self.paused:
            return

        self.sim_time += dt
        self.phase_remaining -= dt

        self.ns_vehicles, self.ew_vehicles = self.counts()
        self.ns_queue, self.ew_queue = self.queue_counts()
        self.ns_near, self.ew_near = self.near_counts()

        self.update_waiting(dt)

        if self.replay_events is not None:
            self.spawn_replay_events()
        else:
            self.spawn_timer -= dt
            if self.spawn_timer <= 0:
                self.spawn_car()
                interval = random.uniform(0.65, 1.60)
                self.spawn_timer = interval / self.manual_density

        for car in self.cars:
            car.update(dt)

        # Remove cars that left the screen
        remaining_cars = []
        for car in self.cars:
            if car.direction == "N" and car.y < self.HEIGHT + 150:
                remaining_cars.append(car)
            elif car.direction == "S" and car.y > -150:
                remaining_cars.append(car)
            elif car.direction == "E" and car.x > -150:
                remaining_cars.append(car)
            elif car.direction == "W" and car.x < self.SIM_WIDTH + 150:
                remaining_cars.append(car)
        self.cars = remaining_cars

        if self.phase_remaining <= 0:
            self.make_ai_decision()

    def reset_for_benchmark(self, fixed_mode, events):
        self.cars.clear()
        self.fixed_time_mode = fixed_mode
        self.phase = "NS"
        self.phase_remaining = 1.0
        self.phase_duration = 1.0
        self.wait_ns = 0.0
        self.wait_ew = 0.0
        self.ns_vehicles = 0
        self.ew_vehicles = 0
        self.ns_queue = 0
        self.ew_queue = 0
        self.total_generated = 0
        self.total_passed = 0
        self.total_wait_time = 0
        self.max_wait_time_recorded = 0.0
        self.completed_wait_times.clear()
        self.completed_system_times.clear()
        self.ml_wait_times.clear()
        self.fixed_wait_times.clear()
        self.sim_time = 0.0
        self.replay_events = events
        self.replay_index = 0
        self.benchmark_active = True
        self.benchmark_wait_sum = 0
        self.benchmark_system_time_sum = 0
        self.benchmark_completed = 0
        self.benchmark_max_wait = 0.0
        self.debug_decisions.clear()
        self.model_predictions_log.clear()
        self.model_inputs_log.clear()
        self.make_ai_decision()

    def draw_roads(self):
        self.screen.fill(BG)

        horizontal = pygame.Rect(0, int(self.CENTER_Y - self.ROAD_W / 2), self.SIM_WIDTH, self.ROAD_W)
        vertical = pygame.Rect(int(self.CENTER_X - self.ROAD_W / 2), 0, self.ROAD_W, self.HEIGHT)

        pygame.draw.rect(self.screen, ROAD_EDGE, horizontal)
        pygame.draw.rect(self.screen, ROAD_EDGE, vertical)

        horizontal_inner = pygame.Rect(0, int(self.CENTER_Y - self.ROAD_W / 2 + 8), self.SIM_WIDTH, self.ROAD_W - 16)
        vertical_inner = pygame.Rect(int(self.CENTER_X - self.ROAD_W / 2 + 8), 0, self.ROAD_W - 16, self.HEIGHT)

        pygame.draw.rect(self.screen, ROAD, horizontal_inner)
        pygame.draw.rect(self.screen, ROAD, vertical_inner)

        # Lane markings
        y1 = int(self.CENTER_Y - self.ROAD_W / 4)
        y2 = int(self.CENTER_Y + self.ROAD_W / 4)
        pygame.draw.line(self.screen, LANE, (0, y1), (self.CENTER_X - self.ROAD_W / 2, y1), 2)
        pygame.draw.line(self.screen, LANE, (self.CENTER_X + self.ROAD_W / 2, y1), (self.SIM_WIDTH, y1), 2)
        pygame.draw.line(self.screen, LANE, (0, y2), (self.CENTER_X - self.ROAD_W / 2, y2), 2)
        pygame.draw.line(self.screen, LANE, (self.CENTER_X + self.ROAD_W / 2, y2), (self.SIM_WIDTH, y2), 2)

        x1 = int(self.CENTER_X - self.ROAD_W / 4)
        x2 = int(self.CENTER_X + self.ROAD_W / 4)
        pygame.draw.line(self.screen, LANE, (x1, 0), (x1, self.CENTER_Y - self.ROAD_W / 2), 2)
        pygame.draw.line(self.screen, LANE, (x1, self.CENTER_Y + self.ROAD_W / 2), (x1, self.HEIGHT), 2)
        pygame.draw.line(self.screen, LANE, (x2, 0), (x2, self.CENTER_Y - self.ROAD_W / 2), 2)
        pygame.draw.line(self.screen, LANE, (x2, self.CENTER_Y + self.ROAD_W / 2), (x2, self.HEIGHT), 2)

        # Stop lines
        stop = self.ROAD_W / 2 + 48
        pygame.draw.line(self.screen, WHITE, (self.CENTER_X - self.ROAD_W / 2, self.CENTER_Y - stop),
                         (self.CENTER_X, self.CENTER_Y - stop), 4)
        pygame.draw.line(self.screen, WHITE, (self.CENTER_X, self.CENTER_Y + stop),
                         (self.CENTER_X + self.ROAD_W / 2, self.CENTER_Y + stop), 4)

    def font(self, size, bold=False):
        return pygame.font.SysFont("DejaVu Sans", size, bold=bold)

    def text(self, value, x, y, size=20, color=BLACK, bold=False):
        surface = self.font(size, bold).render(str(value), True, color)
        self.screen.blit(surface, (x, y))

    def card(self, x, y, width, height, color=LIGHT_GRAY):
        rect = pygame.Rect(x, y, width, height)
        pygame.draw.rect(self.screen, color, rect, border_radius=12)
        pygame.draw.rect(self.screen, (220, 220, 220), rect, 1, border_radius=12)

    def draw_sidebar(self):
        x = self.SIM_WIDTH
        width = self.WIDTH - self.SIM_WIDTH

        pygame.draw.rect(self.screen, (248, 248, 248), (x, 0, width, self.HEIGHT))
        padding = 22

        self.text("SEMÁFORO", x + padding, 20, 27, BLACK, True)
        self.text("INTELIGENTE", x + padding, 52, 27, GREEN, True)

        mode_text = "MODO: TEMPO FIXO" if self.fixed_time_mode else "MODO: MACHINE LEARNING"
        mode_color = RED if self.fixed_time_mode else GREEN
        self.text(mode_text, x + padding, 92, 15, mode_color, True)

        # Scenario card
        card_y = 120
        self.card(x + padding, card_y, width - 2 * padding, 95, LIGHT_GRAY)
        self.text("CENÁRIO", x + padding + 15, card_y + 12, 17, BLACK, True)
        distribution = "80% N/S" if self.traffic_distribution == "NS" else (
            "80% L/O" if self.traffic_distribution == "EW" else "50% / 50%")
        self.text(f"Distribuição: {distribution}", x + padding + 15, card_y + 38, 14, DARK)
        self.text(f"Densidade: {self.manual_density:.2f}x", x + padding + 15, card_y + 61, 14, DARK)

        # North/south card
        card_y = 230
        self.card(x + padding, card_y, width - 2 * padding, 145, LIGHT_BLUE)
        self.text("NORTE / SUL", x + padding + 15, card_y + 12, 19, BLACK, True)
        self.text(f"Carros: {self.ns_vehicles}", x + padding + 15, card_y + 42, 16)
        self.text(f"Fila: {self.ns_queue}", x + padding + 15, card_y + 66, 16)
        self.text(f"Sem verde: {self.wait_ns:.1f}s", x + padding + 15, card_y + 90, 16)
        self.text(f"ML prevê: {self.ns_green_time}s", x + padding + 15, card_y + 114, 16, GREEN, True)

        # East/west card
        card_y = 385
        self.card(x + padding, card_y, width - 2 * padding, 145, LIGHT_GREEN)
        self.text("LESTE / OESTE", x + padding + 15, card_y + 12, 19, BLACK, True)
        self.text(f"Carros: {self.ew_vehicles}", x + padding + 15, card_y + 42, 16)
        self.text(f"Fila: {self.ew_queue}", x + padding + 15, card_y + 66, 16)
        self.text(f"Sem verde: {self.wait_ew:.1f}s", x + padding + 15, card_y + 90, 16)
        self.text(f"ML prevê: {self.ew_green_time}s", x + padding + 15, card_y + 114, 16, GREEN, True)

        # Controller card
        card_y = 540
        self.card(x + padding, card_y, width - 2 * padding, 130, WHITE)
        self.text("CONTROLADOR", x + padding + 15, card_y + 12, 17, BLACK, True)
        self.text(f"Verde: {self.phase}", x + padding + 15, card_y + 39, 18, GREEN, True)
        self.text(f"Restante: {max(0.0, self.phase_remaining):.1f}s", x + padding + 15, card_y + 65, 15)
        reason = self.ai_reason if len(self.ai_reason) <= 39 else self.ai_reason[:39] + "..."
        self.text(reason, x + padding + 15, card_y + 92, 12, DARK)

        # Performance card
        card_y = 680
        self.card(x + padding, card_y, width - 2 * padding, 175, LIGHT_GRAY)
        self.text("DESEMPENHO", x + padding + 15, card_y + 12, 17, BLACK, True)
        cars_per_minute = (self.total_passed / (self.sim_time / 60)) if self.sim_time > 0 else 0
        avg_wait = (sum(self.completed_wait_times) / len(self.completed_wait_times)) if self.completed_wait_times else 0

        self.text(f"Evacuados: {self.total_passed}", x + padding + 15, card_y + 42, 15)
        self.text(f"Fluxo: {cars_per_minute:.1f}/min", x + padding + 15, card_y + 66, 15)
        self.text(f"Espera recente: {avg_wait:.1f}s", x + padding + 15, card_y + 90, 15)
        self.text(f"Na simulação: {len(self.cars)}", x + padding + 15, card_y + 114, 15)

        ml_avg = (sum(self.ml_wait_times) / len(self.ml_wait_times)) if self.ml_wait_times else 0
        fixed_avg = (sum(self.fixed_wait_times) / len(self.fixed_wait_times)) if self.fixed_wait_times else 0
        self.text(f"ML: {ml_avg:.1f}s | Fixo: {fixed_avg:.1f}s", x + padding + 15, card_y + 140, 14, DARK, True)

        # Key hints
        y = min(self.HEIGHT - 105, 875)
        self.text("1 N/S   2 L/O   3 Equilibrado", x + padding, y, 12, DARK)
        self.text("+/- densidade    F ML/Fixo", x + padding, y + 20, 12, DARK)
        self.text("B benchmark único (60s)", x + padding, y + 40, 12, DARK, True)
        self.text("R reinicia    ESPAÇO pausa", x + padding, y + 60, 12, DARK)

    def draw(self):
        self.draw_roads()
        for car in self.cars:
            car.draw(self.screen)

        if self.phase == "NS":
            self.light_ns.draw(self.screen, "GREEN")
            self.light_ew.draw(self.screen, "RED")
            label = "N / S"
        else:
            self.light_ns.draw(self.screen, "RED")
            self.light_ew.draw(self.screen, "GREEN")
            label = "L / O"

        # Label in the middle of the intersection
        surface = self.font(18, True).render(label, True, WHITE)
        text_rect = surface.get_rect(center=(int(self.CENTER_X), int(self.CENTER_Y)))
        bg_rect = text_rect.inflate(25, 14)
        pygame.draw.rect(self.screen, BLACK, bg_rect, border_radius=8)
        self.screen.blit(surface, text_rect)

        self.draw_sidebar()

        if self.paused:
            overlay = pygame.Surface((self.SIM_WIDTH, self.HEIGHT), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 100))
            self.screen.blit(overlay, (0, 0))
            surface = self.font(30, True).render("PAUSADO", True, WHITE)
            self.screen.blit(
                surface,
                (self.SIM_WIDTH // 2 - surface.get_width() // 2, self.HEIGHT // 2)
            )

        pygame.display.flip()


def run_benchmark(screen, base_sim):
    # Run fixed-time and ML on the exact same scenario and compare them
    clock = pygame.time.Clock()
    seed = random.randint(100000, 999999)

    events = generate_scenario(
        seed,
        BENCHMARK_DURATION,
        base_sim.manual_density,
        base_sim.traffic_distribution
    )
    total_scenario_vehicles = len(events)

    # Test 1: fixed-time controller
    fixed_sim = Simulation(screen, fixed_time_mode=True)
    fixed_sim.manual_density = base_sim.manual_density
    fixed_sim.traffic_distribution = base_sim.traffic_distribution
    fixed_sim.reset_for_benchmark(True, events)
    run_benchmark_stage(fixed_sim, screen, clock, "TESTE 1/2: TEMPO FIXO", total_scenario_vehicles)

    f_wait = (
                fixed_sim.benchmark_wait_sum / fixed_sim.benchmark_completed) if fixed_sim.benchmark_completed > 0 else 0.0
    f_flow = fixed_sim.total_passed / (BENCHMARK_DURATION / 60)
    f_evac = fixed_sim.total_passed
    f_gen = fixed_sim.total_generated
    f_rem = max(0, f_gen - f_evac)

    fixed_results = {
        "wait": f_wait,
        "flow": f_flow,
        "evacuated": f_evac,
        "generated": f_gen,
        "remaining": f_rem
    }

    # Test 2: ML controller
    ml_sim = Simulation(screen, fixed_time_mode=False)
    ml_sim.manual_density = base_sim.manual_density
    ml_sim.traffic_distribution = base_sim.traffic_distribution
    ml_sim.reset_for_benchmark(False, events)
    run_benchmark_stage(ml_sim, screen, clock, "TESTE 2/2: MACHINE LEARNING", total_scenario_vehicles)

    m_wait = (ml_sim.benchmark_wait_sum / ml_sim.benchmark_completed) if ml_sim.benchmark_completed > 0 else 0.0
    m_flow = ml_sim.total_passed / (BENCHMARK_DURATION / 60)
    m_evac = ml_sim.total_passed
    m_gen = ml_sim.total_generated
    m_rem = max(0, m_gen - m_evac)

    ml_results = {
        "wait": m_wait,
        "flow": m_flow,
        "evacuated": m_evac,
        "generated": m_gen,
        "remaining": m_rem
    }

    # Percentage change of ML relative to fixed-time
    wait_variation = ((ml_results["wait"] - fixed_results["wait"]) / fixed_results["wait"] * 100) if fixed_results[
                                                                                                         "wait"] > 0 else 0.0
    flow_variation = ((ml_results["flow"] - fixed_results["flow"]) / fixed_results["flow"] * 100) if fixed_results[
                                                                                                         "flow"] > 0 else 0.0

    return {
        "fixed": fixed_results,
        "ml": ml_results,
        "wait_variation": wait_variation,
        "flow_variation": flow_variation,
        "distribution": base_sim.traffic_distribution
    }


def run_benchmark_stage(sim, screen, clock, stage_title, total_scenario_vehicles):
    # Fixed time step so both runs are comparable
    while sim.sim_time < BENCHMARK_DURATION:
        dt = 1.0 / FPS

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    return

        sim.update(dt)
        sim.draw()

        # Progress bar
        progress = sim.sim_time / BENCHMARK_DURATION
        bar_width = int(sim.SIM_WIDTH * 0.8)
        bar_x = (sim.SIM_WIDTH - bar_width) // 2
        bar_y = 15

        pygame.draw.rect(screen, (200, 200, 200), (bar_x, bar_y, bar_width, 18), border_radius=9)
        pygame.draw.rect(screen, GREEN, (bar_x, bar_y, int(bar_width * progress), 18), border_radius=9)
        pygame.draw.rect(screen, BLACK, (bar_x, bar_y, bar_width, 18), 2, border_radius=9)

        progress_text = sim.font(13, True).render(
            f"{stage_title} | Tempo: {sim.sim_time:.1f} / {BENCHMARK_DURATION:.0f}s | Gerados: {sim.total_generated}/{total_scenario_vehicles} | Evacuados: {sim.total_passed}",
            True,
            BLACK
        )
        screen.blit(
            progress_text,
            (bar_x + (bar_width - progress_text.get_width()) // 2, bar_y + 1)
        )

        pygame.display.flip()
        clock.tick(FPS)


def show_benchmark_result_screen(screen, results):
    clock = pygame.time.Clock()
    fixed = results["fixed"]
    ml = results["ml"]
    wait_variation = results["wait_variation"]
    flow_variation = results["flow_variation"]
    distribution = results["distribution"]

    while True:
        screen.fill((250, 250, 250))
        width, height = screen.get_size()

        title_font = pygame.font.SysFont("DejaVu Sans", 26, bold=True)
        subtitle_font = pygame.font.SysFont("DejaVu Sans", 13)
        header_font = pygame.font.SysFont("DejaVu Sans", 17, bold=True)
        cell_font = pygame.font.SysFont("DejaVu Sans", 16)
        value_font = pygame.font.SysFont("DejaVu Sans", 18, bold=True)
        highlight_font = pygame.font.SysFont("DejaVu Sans", 19, bold=True)

        def draw_centered(text, y, font, color=BLACK):
            surf = font.render(str(text), True, color)
            screen.blit(surf, ((width - surf.get_width()) // 2, y))

        draw_centered("COMPARAÇÃO DOS CONTROLADORES", 40, title_font, BLACK)
        dist_label = "80% Norte/Sul" if distribution == "NS" else (
            "80% Leste/Oeste" if distribution == "EW" else "Tráfego Equilibrado")
        draw_centered(f"Cenário: {dist_label} | Duração por teste: {BENCHMARK_DURATION:.0f} segundos", 75,
                      subtitle_font, (100, 100, 100))

        # Results table
        table_width = 820
        table_x = (width - table_width) // 2
        start_y = 125
        row_height = 46

        col_w1 = 340
        col_w2 = 240
        col_w3 = 240

        pygame.draw.rect(screen, (235, 238, 242), (table_x, start_y, table_width, 44), border_radius=8)
        screen.blit(header_font.render("Métrica", True, BLACK), (table_x + 25, start_y + 12))
        screen.blit(header_font.render("TEMPO FIXO", True, (180, 50, 50)), (table_x + col_w1 + 25, start_y + 12))
        screen.blit(header_font.render("ML", True, (30, 130, 60)), (table_x + col_w1 + col_w2 + 25, start_y + 12))

        table_rows = [
            ("Veículos gerados", f"{fixed['generated']}", f"{ml['generated']}"),
            ("Evacuados", f"{fixed['evacuated']}", f"{ml['evacuated']}"),
            ("Restantes", f"{fixed['remaining']}", f"{ml['remaining']}"),
            ("Espera média", f"{fixed['wait']:.1f}s", f"{ml['wait']:.1f}s"),
            ("Fluxo", f"{fixed['flow']:.1f}/min", f"{ml['flow']:.1f}/min")
        ]

        current_y = start_y + 50
        for i, (metric_name, f_val, m_val) in enumerate(table_rows):
            row_bg = (255, 255, 255) if i % 2 == 0 else (245, 247, 250)
            pygame.draw.rect(screen, row_bg, (table_x, current_y, table_width, row_height), border_radius=6)

            screen.blit(cell_font.render(metric_name, True, (40, 40, 40)), (table_x + 25, current_y + 13))
            screen.blit(value_font.render(f_val, True, (120, 30, 30)), (table_x + col_w1 + 25, current_y + 13))
            screen.blit(value_font.render(m_val, True, (20, 100, 40)), (table_x + col_w1 + col_w2 + 25, current_y + 13))

            current_y += row_height + 5

        # Comparison box
        comp_y = current_y + 15
        comp_height = 105
        pygame.draw.rect(screen, (240, 244, 248), (table_x, comp_y, table_width, comp_height), border_radius=10)
        pygame.draw.rect(screen, (210, 220, 230), (table_x, comp_y, table_width, comp_height), 1, border_radius=10)

        screen.blit(highlight_font.render("ANÁLISE COMPARATIVA", True, BLACK), (table_x + 25, comp_y + 16))

        var_text_1 = f"Diferença na espera média: {wait_variation:+.1f}%"
        var_text_2 = f"Diferença no fluxo: {flow_variation:+.1f}%"

        screen.blit(cell_font.render(var_text_1, True, (30, 30, 30)), (table_x + 25, comp_y + 52))
        screen.blit(cell_font.render(var_text_2, True, (30, 30, 30)), (table_x + 440, comp_y + 52))

        draw_centered("Pressione ENTER para voltar", height - 70, subtitle_font, (80, 80, 80))
        draw_centered("Pressione ESC para sair", height - 40, subtitle_font, (120, 120, 120))

        pygame.display.flip()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    return "RESUME"
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()

        clock.tick(30)


def main():
    pygame.init()
    screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
    pygame.display.set_caption("Semáforo Inteligente com Machine Learning")
    clock = pygame.time.Clock()

    simulation = Simulation(screen)
    app_state = "SIMULATION"
    benchmark_results_data = None

    while simulation.running:
        dt = clock.tick(FPS) / 1000.0

        # Keyboard controls (only active during the normal simulation)
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                simulation.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    if app_state == "SIMULATION":
                        simulation.running = False
                elif event.key == pygame.K_SPACE:
                    if app_state == "SIMULATION":
                        simulation.paused = not simulation.paused
                elif event.key == pygame.K_b:
                    if app_state == "SIMULATION":
                        app_state = "RUNNING_BENCHMARK"
                elif event.key == pygame.K_f:
                    if app_state == "SIMULATION":
                        simulation.fixed_time_mode = not simulation.fixed_time_mode
                        simulation.phase_remaining = 0.0
                elif event.key == pygame.K_1:
                    if app_state == "SIMULATION":
                        simulation.traffic_distribution = "NS"
                        simulation.ai_reason = "Cenário: 80% N/S"
                elif event.key == pygame.K_2:
                    if app_state == "SIMULATION":
                        simulation.traffic_distribution = "EW"
                        simulation.ai_reason = "Cenário: 80% L/O"
                elif event.key == pygame.K_3:
                    if app_state == "SIMULATION":
                        simulation.traffic_distribution = "BALANCED"
                        simulation.ai_reason = "Cenário: tráfego equilibrado"
                elif event.key in (pygame.K_PLUS, pygame.K_EQUALS):
                    if app_state == "SIMULATION":
                        simulation.manual_density = clamp(simulation.manual_density + 0.25, 0.25, 3.0)
                elif event.key in (pygame.K_MINUS, pygame.K_KP_MINUS):
                    if app_state == "SIMULATION":
                        simulation.manual_density = clamp(simulation.manual_density - 0.25, 0.25, 3.0)
                elif event.key == pygame.K_r:
                    if app_state == "SIMULATION":
                        simulation = Simulation(screen)

        if app_state == "RUNNING_BENCHMARK":
            benchmark_results_data = run_benchmark(screen, simulation)
            app_state = "SHOWING_RESULTS"

        elif app_state == "SHOWING_RESULTS":
            action = show_benchmark_result_screen(screen, benchmark_results_data)
            if action == "RESUME":
                # Keep the current settings when returning to the simulation
                density = simulation.manual_density
                distribution = simulation.traffic_distribution
                simulation = Simulation(screen)
                simulation.manual_density = density
                simulation.traffic_distribution = distribution
                app_state = "SIMULATION"

        elif app_state == "SIMULATION":
            simulation.update(dt)
            simulation.draw()

    pygame.quit()


if __name__ == "__main__":
    main()