import tkinter as tk
from tkinter import ttk
import random
import time
import joblib

MODEL_PATH = "models/traffic_model.joblib"

class TrafficSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Semáforo Inteligente - Machine Learning")
        self.root.geometry("1000x720")
        self.root.resizable(False, False)

        self.model = joblib.load(MODEL_PATH)

        self.running = False
        self.phase = "NS_GREEN"
        self.remaining = 10
        self.last_update = time.time()

        # Quantidade de veículos simulados em cada direção.
        self.north = 8
        self.south = 5
        self.east = 18
        self.west = 12

        self.wait_ns = 0
        self.wait_ew = 0

        self.build_ui()
        self.update_canvas()

    def build_ui(self):
        self.canvas = tk.Canvas(
            self.root, width=700, height=600, bg="#dddddd"
        )
        self.canvas.pack(side="left", padx=10, pady=10)

        panel = ttk.Frame(self.root, padding=10)
        panel.pack(side="right", fill="y")

        ttk.Label(
            panel,
            text="SEMÁFORO INTELIGENTE",
            font=("Arial", 16, "bold")
        ).pack(pady=10)

        self.status = ttk.Label(panel, text="Sistema parado")
        self.status.pack(pady=5)

        self.phase_label = ttk.Label(
            panel, text="", font=("Arial", 12, "bold")
        )
        self.phase_label.pack(pady=10)

        self.timer_label = ttk.Label(
            panel, text="", font=("Arial", 20)
        )
        self.timer_label.pack(pady=10)

        self.info = ttk.Label(
            panel,
            text="",
            justify="left",
            font=("Arial", 10)
        )
        self.info.pack(pady=10)

        ttk.Button(
            panel, text="Iniciar simulação", command=self.start
        ).pack(fill="x", pady=5)

        ttk.Button(
            panel, text="Adicionar tráfego", command=self.add_traffic
        ).pack(fill="x", pady=5)

        ttk.Button(
            panel, text="Resetar", command=self.reset
        ).pack(fill="x", pady=5)

        ttk.Label(
            panel,
            text=(
                "O modelo prevê o tempo de verde\n"
                "com base no fluxo observado."
            ),
            justify="center"
        ).pack(pady=30)

    def predict_green_time(self, vehicle_count, waiting_time, opposite_count):
        prediction = self.model.predict([[
            vehicle_count, waiting_time, opposite_count
        ]])[0]
        return max(10, min(60, int(round(prediction))))

    def current_counts(self):
        if self.phase == "NS_GREEN":
            return self.north + self.south, self.east + self.west
        return self.east + self.west, self.north + self.south

    def decide_next_phase(self):
        ns = self.north + self.south
        ew = self.east + self.west

        if self.phase == "NS_GREEN":
            waiting = self.wait_ew
            green = self.predict_green_time(ew, waiting, ns)
            self.phase = "EW_GREEN"
        else:
            waiting = self.wait_ns
            green = self.predict_green_time(ns, waiting, ew)
            self.phase = "NS_GREEN"

        self.remaining = green

    def start(self):
        if not self.running:
            self.running = True
            self.status.config(text="Simulação em execução")
            self.last_update = time.time()
            self.tick()

    def tick(self):
        if not self.running:
            return

        now = time.time()

        if now - self.last_update >= 1:
            self.last_update = now

            # Novos veículos chegam aleatoriamente.
            self.north += random.randint(0, 3)
            self.south += random.randint(0, 2)
            self.east += random.randint(0, 3)
            self.west += random.randint(0, 2)

            # A direção vermelha acumula espera.
            if self.phase == "NS_GREEN":
                self.wait_ew += 1
                self.wait_ns = max(0, self.wait_ns - 1)
                self.north = max(0, self.north - random.randint(0, 2))
                self.south = max(0, self.south - random.randint(0, 2))
            else:
                self.wait_ns += 1
                self.wait_ew = max(0, self.wait_ew - 1)
                self.east = max(0, self.east - random.randint(0, 2))
                self.west = max(0, self.west - random.randint(0, 2))

            self.remaining -= 1

            if self.remaining <= 0:
                self.decide_next_phase()

            self.update_canvas()

        self.root.after(100, self.tick)

    def add_traffic(self):
        self.north += random.randint(5, 15)
        self.south += random.randint(5, 15)
        self.east += random.randint(5, 15)
        self.west += random.randint(5, 15)
        self.update_canvas()

    def reset(self):
        self.running = False
        self.phase = "NS_GREEN"
        self.remaining = 10
        self.north, self.south = 8, 5
        self.east, self.west = 18, 12
        self.wait_ns = self.wait_ew = 0
        self.status.config(text="Sistema parado")
        self.update_canvas()

    def draw_traffic_light(self, x, y, green):
        self.canvas.create_rectangle(
            x, y, x + 70, y + 180, fill="black"
        )

        red_fill = "#333333" if green else "red"
        green_fill = "green" if green else "#333333"

        self.canvas.create_oval(x+15, y+15, x+55, y+55, fill=red_fill)
        self.canvas.create_oval(x+15, y+115, x+55, y+155, fill=green_fill)

    def update_canvas(self):
        self.canvas.delete("all")

        # Cruzamento.
        self.canvas.create_rectangle(
            0, 230, 700, 370, fill="#555555"
        )
        self.canvas.create_rectangle(
            280, 0, 420, 600, fill="#555555"
        )

        # Faixas.
        for x in range(0, 700, 40):
            self.canvas.create_rectangle(
                x, 298, x+20, 302, fill="white"
            )

        for y in range(0, 600, 40):
            self.canvas.create_rectangle(
                348, y, 352, y+20, fill="white"
            )

        # Semáforos.
        self.draw_traffic_light(
            250, 160, self.phase == "NS_GREEN"
        )
        self.draw_traffic_light(
            430, 380, self.phase == "EW_GREEN"
        )

        # Contagens.
        self.canvas.create_text(
            350, 25,
            text=f"NORTE: {self.north} veículos",
            font=("Arial", 14, "bold")
        )
        self.canvas.create_text(
            350, 575,
            text=f"SUL: {self.south} veículos",
            font=("Arial", 14, "bold")
        )
        self.canvas.create_text(
            90, 300,
            text=f"OESTE: {self.west}",
            font=("Arial", 14, "bold")
        )
        self.canvas.create_text(
            610, 300,
            text=f"LESTE: {self.east}",
            font=("Arial", 14, "bold")
        )

        phase_text = (
            "NORTE/SUL — VERDE"
            if self.phase == "NS_GREEN"
            else "LESTE/OESTE — VERDE"
        )
        self.phase_label.config(text=phase_text)
        self.timer_label.config(text=f"{self.remaining}s")

        self.info.config(
            text=(
                f"Norte: {self.north}\n"
                f"Sul: {self.south}\n"
                f"Leste: {self.east}\n"
                f"Oeste: {self.west}\n\n"
                f"Espera N/S: {self.wait_ns}s\n"
                f"Espera L/O: {self.wait_ew}s"
            )
        )

if __name__ == "__main__":
    root = tk.Tk()
    app = TrafficSimulator(root)
    root.mainloop()
