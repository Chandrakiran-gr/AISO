"""
Sim 6 — OOP rebuild with control console.
Same idea as sim_6: evolution sim with neural net cells, food, walls.
All magic numbers live in Config and are editable in the Console window.
"""

import random
import tkinter as tk
from tkinter import ttk
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# -----------------------------------------------------------------------------
# CONFIG — all tunable numbers (console edits these)
# -----------------------------------------------------------------------------
@dataclass
class Config:
    """All magic numbers in one place. Console window edits these."""
    # Grid
    size: int = 60
    cell_size: int = 8

    # Food
    food_spawn_per_10k: int = 400      # chance per 10000 to spawn food on empty cell
    target_pop: int = 120
    food_from_kill: int = 800
    food_amount: int = 440             # energy from eating one food

    # Timing / cleanup
    cleanup_cycles: int = 60
    cycle_time_ms: int = 100

    # Combat
    kill_enabled: bool = True

    # Brain
    hidden_neurons: int = 40
    mutation_per_10k: int = 20         # per 10000 chance to mutate a weight

    # Cell lifecycle
    reproduce_cost: int = 3000
    food_burn_per_tick: int = 110
    food_start: int = 700              # energy for new cells
    initial_energy: int = 206000       # first cell

    def to_entries(self) -> List[Tuple[str, str, type]]:
        """For console: (label, current_value_str, type)."""
        return [
            ("size", str(self.size), int),
            ("cell_size", str(self.cell_size), int),
            ("food_spawn_per_10k", str(self.food_spawn_per_10k), int),
            ("target_pop", str(self.target_pop), int),
            ("food_from_kill", str(self.food_from_kill), int),
            ("food_amount", str(self.food_amount), int),
            ("cleanup_cycles", str(self.cleanup_cycles), int),
            ("cycle_time_ms", str(self.cycle_time_ms), int),
            ("kill_enabled", "1" if self.kill_enabled else "0", bool),
            ("hidden_neurons", str(self.hidden_neurons), int),
            ("mutation_per_10k", str(self.mutation_per_10k), int),
            ("reproduce_cost", str(self.reproduce_cost), int),
            ("food_burn_per_tick", str(self.food_burn_per_tick), int),
            ("food_start", str(self.food_start), int),
            ("initial_energy", str(self.initial_energy), int),
        ]

    def apply_from_entries(self, values: dict):
        """Apply dict of name -> str value back into config."""
        for key, val in values.items():
            if not hasattr(self, key):
                continue
            t = type(getattr(self, key))
            if t is bool:
                setattr(self, key, val.strip() in ("1", "true", "yes"))
            else:
                try:
                    setattr(self, key, t(val))
                except (ValueError, TypeError):
                    pass


# -----------------------------------------------------------------------------
# CONSOLE — window to view/edit all config
# -----------------------------------------------------------------------------
class Console:
    """Toplevel window with an entry for each config value. Apply pushes to config."""

    def __init__(self, config: Config, parent: Optional[tk.Tk] = None):
        self.config = config
        self.win = tk.Toplevel(parent) if parent else tk.Tk()
        self.win.title("Console — Sim Params")
        self.entries: dict = {}
        self._build()

    def _build(self):
        frame = ttk.Frame(self.win, padding=10)
        frame.pack(fill=tk.BOTH, expand=True)
        for label, val, _ in self.config.to_entries():
            row = ttk.Frame(frame)
            row.pack(fill=tk.X, pady=2)
            ttk.Label(row, text=label, width=22, anchor=tk.W).pack(side=tk.LEFT)
            e = ttk.Entry(row, width=12)
            e.insert(0, val)
            e.pack(side=tk.LEFT, padx=4)
            self.entries[label] = e
        ttk.Button(frame, text="Apply", command=self._apply).pack(pady=10)

    def _apply(self):
        values = {k: e.get() for k, e in self.entries.items()}
        self.config.apply_from_entries(values)


# -----------------------------------------------------------------------------
# WORLD — grid of tiles (empty, wall, food, or cell id)
# -----------------------------------------------------------------------------
class World:
    EMPTY = "not"
    WALL = "wall"
    FOOD = "food"

    def __init__(self, config: Config):
        self.config = config
        self.size = config.size
        self.grid: dict = {}  # (x,y) -> "not" | "wall" | "food" | "cell_{id}"
        self.clear()

    def clear(self):
        for i in range(self.size):
            for j in range(self.size):
                self.grid[i, j] = self.EMPTY

    def get(self, x: int, y: int) -> str:
        if 0 <= x < self.size and 0 <= y < self.size:
            return self.grid.get((x, y), self.EMPTY)
        return self.WALL

    def set(self, x: int, y: int, value: str):
        if 0 <= x < self.size and 0 <= y < self.size:
            self.grid[x, y] = value

    def count_neighbors(self, x: int, y: int, tile: str) -> int:
        n = 0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                if self.get(x + dx, y + dy) == tile:
                    n += 1
        return n


# -----------------------------------------------------------------------------
# BRAIN — 25 inputs (5x5), hidden, 9 outputs (0-7 move, 8 kill, 9 reproduce)
# -----------------------------------------------------------------------------
class Brain:
    INPUTS = 25
    OUTPUTS = 9

    def __init__(self, config: Config, parent_weights: Optional[Tuple] = None):
        self.config = config
        n = config.hidden_neurons
        if parent_weights is None:
            self.w_in = [[0.0] * Brain.INPUTS for _ in range(n)]
            self.w_out = [[0.0] * n for _ in range(Brain.OUTPUTS)]
            self._randomize_weights()
        else:
            self.w_in = [[x for x in row] for row in parent_weights[0]]
            self.w_out = [[x for x in row] for row in parent_weights[1]]
            self._mutate()

    def _randomize_weights(self):
        mut = self.config.mutation_per_10k
        for i in range(len(self.w_in)):
            for j in range(len(self.w_in[0])):
                if random.randint(0, 9999) < mut:
                    self.w_in[i][j] += random.randint(-9, 9) / 100 + random.choice([-0.1, 0, 0, 0, 0, 0, 0, 0.1])
        for i in range(len(self.w_out)):
            for j in range(len(self.w_out[0])):
                if random.randint(0, 9999) < mut:
                    self.w_out[i][j] += random.randint(-9, 9) / 100 + random.choice([-0.1, 0, 0, 0, 0, 0, 0.1])

    def _mutate(self):
        mut = self.config.mutation_per_10k
        for i in range(len(self.w_in)):
            for j in range(len(self.w_in[0])):
                if random.randint(0, 9999) < mut:
                    self.w_in[i][j] += random.randint(-3, 3) / 100 + random.choice([-0.1, 0, 0, 0, 0, 0, 0, 0.1])
        for i in range(len(self.w_out)):
            for j in range(len(self.w_out[0])):
                if random.randint(0, 9999) < mut:
                    self.w_out[i][j] += random.randint(-9, 9) / 100 + random.choice([-0.1, 0, 0, 0, 0, 0, 0.1])

    @staticmethod
    def clamp(x: float) -> float:
        if x < 0:
            return 0
        if x > 1000:
            return 1000
        return x

    def decide(self, world: World, cx: int, cy: int, energy: float, burn: int) -> int:
        """Returns 0-7 move, 8 kill, 9 reproduce."""
        cfg = self.config
        if energy > cfg.reproduce_cost + burn * 3:
            return 9
        inputs = []
        for dy in range(-2, 3):
            for dx in range(-2, 3):
                t = world.get(cx + dx, cy + dy)
                if t == "cell" or t.startswith("cell_"):
                    inputs.append(0)
                elif t == world.WALL:
                    inputs.append(0)
                elif t == world.EMPTY:
                    inputs.append(300)
                elif t == world.FOOD:
                    inputs.append(1000)
                else:
                    inputs.append(333)
        n = cfg.hidden_neurons
        mid = [0.0] * n
        for i in range(n):
            for j in range(Brain.INPUTS):
                mid[i] += inputs[j] * self.w_in[i][j]
            mid[i] = Brain.clamp(mid[i])
        out = [0.0] * Brain.OUTPUTS
        for i in range(Brain.OUTPUTS):
            for j in range(n):
                out[i] += mid[j] * self.w_out[i][j]
        best = 0
        for i in range(1, Brain.OUTPUTS):
            if out[i] > out[best]:
                best = i
        return best


# -----------------------------------------------------------------------------
# CELL
# -----------------------------------------------------------------------------
CELL_COLORS = [
    "pink", "blue", "yellow", "red", "purple", "lime", "lightblue", "orange",
    "darkred", "darkblue", "darkgreen", "hotpink", "#1A1B55", "#0C10FF",
    "#E0FF0C", "#2EC691", "#C6592E", "#9AECF4", "#D19AF4", "#6C1AA0",
    "#FF00CA", "#674F62", "#57FF00", "brown",
]


class Cell:
    def __init__(self, cell_id: int, x: int, y: int, energy: float, burn: int,
                 config: Config, parent: Optional["Cell"] = None):
        self.id = cell_id
        self.x = x
        self.y = y
        self.energy = energy
        self.burn = burn
        self.config = config
        self.alive = True
        if parent is None:
            self.color = random.choice(CELL_COLORS)
            self.brain = Brain(config, None)
        else:
            self.color = parent.color if random.randint(0, 40) != 3 else random.choice(CELL_COLORS)
            self.brain = Brain(config, (parent.brain.w_in, parent.brain.w_out))

    def tick(self, world: World, cells: List["Cell"]) -> Optional[Tuple[str, int, int]]:
        """Returns (action, dx_or_0, dy_or_0) for move, or None for reproduce/kill handled elsewhere."""
        self.energy -= self.burn
        if self.energy < 0:
            self.alive = False
            return ("die", self.x, self.y)
        decision = self.brain.decide(world, self.x, self.y, self.energy, self.burn)
        if decision <= 7:
            dx = [1, 1, 0, -1, -1, -1, 0, 1][decision]
            dy = [0, 1, 1, 1, 0, -1, -1, -1][decision]
            return ("move", self.x + dx, self.y + dy)
        if decision == 8:
            return ("kill", self.x, self.y)
        if decision == 9:
            return ("reproduce", self.x, self.y)
        return None


# -----------------------------------------------------------------------------
# SIMULATION
# -----------------------------------------------------------------------------
def dig(seed: int, n: int) -> int:
    return seed // 10 ** n % 10


class Sim:
    def __init__(self, config: Config):
        self.config = config
        self.world = World(config)
        self.cells: List[Cell] = []
        self.cell_counter = 0
        self.cycle = 0

    def build_map(self, seed: int):
        self.world.clear()
        s = seed
        # Simplified wall gen: border + some random
        for i in range(self.world.size):
            for j in range(self.world.size):
                if i == 0 or i == self.world.size - 1 or j == 0 or j == self.world.size - 1:
                    self.world.set(i, j, World.WALL)
                else:
                    self.world.set(i, j, World.EMPTY)
        # Place some walls from seed
        r = dig(s, 0) + dig(s, 9)
        for _ in range(3):
            for i in range(1, self.world.size - 1):
                for j in range(1, self.world.size - 1):
                    if random.randint(1, 100) <= r:
                        self.world.set(i, j, World.WALL)

    def build_food(self, seed: int):
        for i in range(self.world.size):
            for j in range(self.world.size):
                if self.world.get(i, j) == World.FOOD:
                    self.world.set(i, j, World.EMPTY)
        s = seed
        for i in range(self.world.size):
            for j in range(self.world.size):
                if self.world.get(i, j) == World.EMPTY and random.randint(1, 100) <= 30:
                    self.world.set(i, j, World.FOOD)

    def spawn_food(self):
        cfg = self.config
        for i in range(self.world.size):
            for j in range(self.world.size):
                if cfg.food_spawn_per_10k > random.randint(0, 9999):
                    if self.world.get(i, j) == World.EMPTY:
                        self.world.set(i, j, World.FOOD)

    def add_cell(self, x: int, y: int, energy: float, parent: Optional[Cell] = None) -> Optional[Cell]:
        if self.world.get(x, y) not in (World.EMPTY, World.FOOD):
            return None
        self.cell_counter += 1
        cid = self.cell_counter
        burn = self.config.food_burn_per_tick
        start = self.config.food_start
        cell = Cell(cid, x, y, energy if parent is None else start, burn, self.config, parent)
        if self.world.get(x, y) == World.FOOD:
            cell.energy += self.config.food_amount
        self.world.set(x, y, f"cell_{cid}")
        self.cells.append(cell)
        return cell

    def run_tick(self):
        cfg = self.config
        self.spawn_food()
        moves = []
        reproduces = []
        kills = []
        for c in self.cells:
            if not c.alive:
                continue
            result = c.tick(self.world, self.cells)
            if result is None:
                continue
            action, nx, ny = result
            if action == "die":
                self.world.set(c.x, c.y, World.EMPTY)
                continue
            if action == "move":
                if 0 <= nx < self.world.size and 0 <= ny < self.world.size:
                    tile = self.world.get(nx, ny)
                    if tile == World.EMPTY or tile == World.FOOD:
                        moves.append((c, nx, ny, tile == World.FOOD))
            elif action == "reproduce" and c.energy >= cfg.reproduce_cost:
                reproduces.append(c)
            elif action == "kill" and cfg.kill_enabled:
                kills.append(c)

        for c, nx, ny, ate_food in moves:
            self.world.set(c.x, c.y, World.EMPTY)
            c.x, c.y = nx, ny
            if ate_food:
                c.energy += cfg.food_amount
            self.world.set(nx, ny, f"cell_{c.id}")

        for c in kills:
            for other in self.cells:
                if not other.alive or other.id == c.id:
                    continue
                if abs(other.x - c.x) <= 1 and abs(other.y - c.y) <= 1:
                    other.alive = False
                    self.world.set(other.x, other.y, World.EMPTY)
                    c.energy += cfg.food_from_kill

        for c in reproduces:
            if c.energy < cfg.reproduce_cost:
                continue
            c.energy -= cfg.reproduce_cost
            for _ in range(500):
                dx = random.randint(-2, 2)
                dy = random.randint(-2, 2)
                if dx == 0 and dy == 0:
                    continue
                nx, ny = c.x + dx, c.y + dy
                if 0 <= nx < self.world.size and 0 <= ny < self.world.size:
                    if self.world.get(nx, ny) in (World.EMPTY, World.FOOD):
                        self.add_cell(nx, ny, cfg.food_start, c)
                        break

        self.cells = [c for c in self.cells if c.alive]
        self.cycle += 1


# -----------------------------------------------------------------------------
# UI
# -----------------------------------------------------------------------------
class SimApp:
    def __init__(self):
        self.config = Config()
        self.root = tk.Tk()
        self.root.title("Sim 6 OOP")
        self.sim: Optional[Sim] = None
        self.started = False
        self.console: Optional[Console] = None
        self.canvas: Optional[tk.Canvas] = None
        self.control_entries: dict = {}
        self._build_ui()

    def _build_ui(self):
        cfg = self.config
        w = cfg.size * cfg.cell_size

        # Left: canvas + start / seeds
        left = ttk.Frame(self.root, padding=5)
        left.grid(row=0, column=0, sticky=tk.N)
        self.canvas = tk.Canvas(left, width=w, height=w, bg="black")
        self.canvas.pack()
        ttk.Button(left, text="Start", command=self._start).pack(pady=4)
        ttk.Label(left, text="Map seed").pack()
        self.seed_map = ttk.Entry(left, width=16)
        self.seed_map.insert(0, "904885159962")
        self.seed_map.pack(pady=2)
        ttk.Label(left, text="Food seed").pack()
        self.seed_food = ttk.Entry(left, width=16)
        self.seed_food.insert(0, "7240199706")
        self.seed_food.pack(pady=2)

        # Right: control panel — all magic numbers
        right = ttk.LabelFrame(self.root, text="Control panel — magic numbers", padding=8)
        right.grid(row=0, column=1, sticky=tk.N + tk.W, padx=10, pady=5)
        inner = ttk.Frame(right)
        inner.pack()
        for i, (label, val, _) in enumerate(cfg.to_entries()):
            ttk.Label(inner, text=label, width=20, anchor=tk.W).grid(row=i, column=0, sticky=tk.W, pady=1)
            e = ttk.Entry(inner, width=10)
            e.insert(0, val)
            e.grid(row=i, column=1, padx=4, pady=1)
            self.control_entries[label] = e
        ttk.Button(right, text="Apply", command=self._apply_control).pack(pady=8)

    def _apply_control(self):
        values = {k: e.get() for k, e in self.control_entries.items()}
        self.config.apply_from_entries(values)
        if self.sim is not None:
            self.sim.config = self.config
            self.sim.world.config = self.config
            for c in self.sim.cells:
                c.config = self.config
                c.brain.config = self.config

    def _start(self):
        if self.started:
            return
        self.started = True
        cfg = self.config
        self.sim = Sim(cfg)
        try:
            self.sim.build_map(int(self.seed_map.get()))
            self.sim.build_food(int(self.seed_food.get()))
        except ValueError:
            self.sim.build_map(904885159962)
            self.sim.build_food(7240199706)
        for _ in range(1):
            while True:
                x = random.randint(2, cfg.size - 3)
                y = random.randint(2, cfg.size - 3)
                if self.sim.world.get(x, y) in (World.EMPTY, World.FOOD):
                    self.sim.add_cell(x, y, cfg.initial_energy, None)
                    break
        self._draw()
        self._tick()

    def _draw(self):
        if self.sim is None or self.canvas is None:
            return
        cfg = self.config
        cs = cfg.cell_size
        self.canvas.delete("all")
        for i in range(cfg.size):
            for j in range(cfg.size):
                t = self.sim.world.get(i, j)
                if t == World.WALL:
                    col = "gray"
                elif t == World.FOOD:
                    col = "limegreen"
                elif t == World.EMPTY:
                    col = "white"
                else:
                    cid = int(t.replace("cell_", ""))
                    cell = next((c for c in self.sim.cells if c.id == cid), None)
                    col = cell.color if cell else "red"
                self.canvas.create_rectangle(i * cs, j * cs, (i + 1) * cs, (j + 1) * cs, fill=col, outline="")

    def _tick(self):
        if not self.started or self.sim is None:
            return
        self.sim.run_tick()
        self._draw()
        self.root.after(self.config.cycle_time_ms, self._tick)

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = SimApp()
    app.run()
