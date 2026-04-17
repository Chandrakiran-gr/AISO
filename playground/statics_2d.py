"""
2D Statics Engine - Interactive truss editor and solver.
Click to add nodes, drag between nodes for members, click nodes for supports/loads.
"""

import tkinter as tk
from tkinter import simpledialog, messagebox
import math
import numpy as np


def solve_truss(nodes, members, supports, loads):
    """
    Solve 2D determinate truss using method of joints.
    loads: dict {node_idx: (Fx, Fy)}
    Returns: (member_forces, reactions, success)
    """
    n_nodes = len(nodes)
    n_members = len(members)

    n_reactions = 0
    reaction_map = {}
    for node_idx, supp_type in supports.items():
        if supp_type == 'pin':
            reaction_map[(node_idx, 'Rx')] = n_reactions
            n_reactions += 1
            reaction_map[(node_idx, 'Ry')] = n_reactions
            n_reactions += 1
        elif supp_type == 'roller_x':
            reaction_map[(node_idx, 'Ry')] = n_reactions
            n_reactions += 1
        elif supp_type == 'roller_y':
            reaction_map[(node_idx, 'Rx')] = n_reactions
            n_reactions += 1

    n_unknowns = n_members + n_reactions
    n_equations = 2 * n_nodes

    if n_equations != n_unknowns:
        return None, None, False

    # Clear failure reason for UI
    solve_truss.last_error = (
        "Statically indeterminate (2J < M + R)" if n_equations < n_unknowns
        else "Unstable / under-restrained (2J > M + R)"
    )
    A = np.zeros((n_equations, n_unknowns))
    b = np.zeros(n_equations)

    def get_member_info(m_idx):
        i, j = members[m_idx]
        xi, yi = nodes[i]
        xj, yj = nodes[j]
        L = math.hypot(xj - xi, yj - yi)
        if L < 1e-10:
            return 0, 0, 0
        cx = (xj - xi) / L
        cy = (yj - yi) / L
        return L, cx, cy

    for joint in range(n_nodes):
        eq_x, eq_y = 2 * joint, 2 * joint + 1
        Px, Py = loads.get(joint, (0, 0))
        b[eq_x], b[eq_y] = -Px, -Py

        for m_idx, (i, j) in enumerate(members):
            if i != joint and j != joint:
                continue
            _, cx, cy = get_member_info(m_idx)
            if cx == 0 and cy == 0:
                continue
            sign = 1 if joint == i else -1
            A[eq_x, m_idx] = sign * cx
            A[eq_y, m_idx] = sign * cy

        if joint in supports:
            supp = supports[joint]
            if supp == 'pin':
                A[eq_x, n_members + reaction_map[(joint, 'Rx')]] = 1
                A[eq_y, n_members + reaction_map[(joint, 'Ry')]] = 1
            elif supp == 'roller_x':
                A[eq_y, n_members + reaction_map[(joint, 'Ry')]] = 1
            elif supp == 'roller_y':
                A[eq_x, n_members + reaction_map[(joint, 'Rx')]] = 1

    try:
        x = np.linalg.solve(A, b)
        member_forces = x[:n_members]
        reactions = {}
        for (node, comp), idx in reaction_map.items():
            if node not in reactions:
                reactions[node] = {}
            reactions[node][comp] = x[n_members + idx]
        return member_forces, reactions, True
    except np.linalg.LinAlgError:
        solve_truss.last_error = "Singular matrix (unstable or bad geometry)"
        return None, None, False


# Snap distance for clicking on nodes
NODE_RADIUS = 12


class StaticsEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("2D Statics Engine")
        self.root.configure(bg="#1e1e2e")

        self.canvas_width = 800
        self.canvas_height = 550

        # Start blank
        self.nodes = []
        self.members = []
        self.supports = {}
        self.loads = {}
        self.moments = {}

        self.member_forces = None
        self.reactions = None
        self.solved = False

        self.tool = "node"
        self.member_first = None
        self.drag_start = None

        # Layout
        main = tk.Frame(root, padx=10, pady=10, bg="#1e1e2e")
        main.pack(fill=tk.BOTH, expand=True)

        toolbar = tk.Frame(main, bg="#313244", padx=8, pady=6)
        toolbar.pack(fill=tk.X, pady=(0, 8))

        btn_style = {"font": ("Consolas", 10), "relief": tk.FLAT, "padx": 12, "pady": 6, "cursor": "hand2"}

        tools = [
            ("node", "Node", "#a6e3a1"),
            ("member", "Member", "#89b4fa"),
            ("pin", "Pin", "#f9e2af"),
            ("roller", "Roller", "#fab387"),
            ("force", "Force", "#f38ba8"),
            ("moment", "Moment", "#cba6f7"),
            ("delete", "Delete", "#f38ba8"),
        ]

        self.tool_btns = {}
        for key, label, color in tools:
            b = tk.Button(toolbar, text=label, command=lambda k=key: self.set_tool(k),
                         bg=color, fg="#1e1e2e", **btn_style)
            b.pack(side=tk.LEFT, padx=2)
            self.tool_btns[key] = b

        tk.Button(toolbar, text="Solve", command=self.solve, bg="#89b4fa", fg="#1e1e2e",
                  font=("Consolas", 11), padx=15, pady=6, relief=tk.FLAT, cursor="hand2").pack(side=tk.LEFT, padx=10)

        self.status = tk.Label(toolbar, text="Node tool: click canvas to add. Member: drag between nodes.",
                              font=("Consolas", 10), fg="#a6adc8", bg="#313244")
        self.status.pack(side=tk.LEFT, padx=15)

        self.canvas = tk.Canvas(
            main, width=self.canvas_width, height=self.canvas_height,
            bg="#2d2d3d", highlightthickness=1, highlightbackground="#45475a"
        )
        self.canvas.pack()

        self.canvas.bind("<Button-1>", self.on_click)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)

        self.set_tool("node")
        self.draw()

    def set_tool(self, tool):
        self.tool = tool
        self.member_first = None
        for k, b in self.tool_btns.items():
            b.configure(relief=tk.RAISED if k == tool else tk.FLAT, bd=2 if k == tool else 0)
        hints = {
            "node": "Click canvas to add node",
            "member": "Click node A, then node B (or drag between nodes)",
            "pin": "Click node to add/remove pin support",
            "roller": "Click node to add roller support",
            "force": "Click node to add force (Fx, Fy)",
            "moment": "Click node to add moment (truss: display only)",
            "delete": "Click node or member to delete",
        }
        self.status.config(text=hints.get(tool, ""))

    def find_node_at(self, x, y):
        for i, (nx, ny) in enumerate(self.nodes):
            if math.hypot(x - nx, y - ny) <= NODE_RADIUS:
                return i
        return None

    def find_member_at(self, x, y):
        for m_idx, (i, j) in enumerate(self.members):
            x1, y1 = self.nodes[i]
            x2, y2 = self.nodes[j]
            # Distance from point to line segment
            px, py = x - x1, y - y1
            dx, dy = x2 - x1, y2 - y1
            L = math.hypot(dx, dy)
            if L < 1e-6:
                d = math.hypot(px, py)
            else:
                t = max(0, min(1, (px * dx + py * dy) / (L * L)))
                projx, projy = x1 + t * dx, y1 + t * dy
                d = math.hypot(x - projx, y - projy)
            if d <= 8:
                return m_idx
        return None

    def on_click(self, event):
        x, y = event.x, event.y

        if self.tool == "node":
            self.nodes.append((x, y))
            self.solved = False
            self.draw()

        elif self.tool == "member":
            n = self.find_node_at(x, y)
            if n is not None:
                if self.member_first is None:
                    self.member_first = n
                    self.status.config(text=f"Member: now click second node (from {n})")
                else:
                    if n != self.member_first and (self.member_first, n) not in self.members and (n, self.member_first) not in self.members:
                        self.members.append((self.member_first, n))
                        self.solved = False
                    self.member_first = None
                    self.set_tool("member")

        elif self.tool == "pin":
            n = self.find_node_at(x, y)
            if n is not None:
                if self.supports.get(n) == 'pin':
                    del self.supports[n]
                else:
                    self.supports[n] = 'pin'
                self.solved = False
                self.draw()

        elif self.tool == "roller":
            n = self.find_node_at(x, y)
            if n is not None:
                if self.supports.get(n) == 'roller_x':
                    del self.supports[n]
                else:
                    self.supports[n] = 'roller_x'
                self.solved = False
                self.draw()

        elif self.tool == "force":
            n = self.find_node_at(x, y)
            if n is not None:
                Fx = simpledialog.askfloat("Force Fx", "Fx (horizontal, + right):", initialvalue=0)
                if Fx is None:
                    return
                Fy = simpledialog.askfloat("Force Fy", "Fy (vertical, + down):", initialvalue=-100)
                if Fy is None:
                    return
                self.loads[n] = (Fx, Fy)
                self.solved = False
                self.draw()

        elif self.tool == "moment":
            n = self.find_node_at(x, y)
            if n is not None:
                M = simpledialog.askfloat("Moment", "M (counter-clockwise +):", initialvalue=0)
                if M is not None:
                    self.moments[n] = M
                    self.draw()

        elif self.tool == "delete":
            n = self.find_node_at(x, y)
            m = self.find_member_at(x, y)
            if n is not None:
                self.delete_node(n)
            elif m is not None:
                self.members.pop(m)
                self.solved = False
                self.draw()

    def delete_node(self, i):
        self.nodes.pop(i)
        self.members = [(a if a < i else a - 1, b if b < i else b - 1)
                        for a, b in self.members if a != i and b != i]
        self.supports = {a if a < i else a - 1: v for a, v in self.supports.items() if a != i}
        self.loads = {a if a < i else a - 1: v for a, v in self.loads.items() if a != i}
        self.moments = {a if a < i else a - 1: v for a, v in self.moments.items() if a != i}
        self.solved = False
        self.draw()

    def on_drag(self, event):
        if self.tool == "member" and self.member_first is not None:
            self.drag_start = (event.x, event.y)
        self.draw_preview(event.x, event.y)

    def on_release(self, event):
        if self.tool == "member" and self.member_first is not None and self.drag_start:
            n = self.find_node_at(event.x, event.y)
            if n is not None and n != self.member_first:
                pair = (self.member_first, n)
                if pair not in self.members and (n, self.member_first) not in self.members:
                    self.members.append(pair)
                    self.solved = False
            self.member_first = None
            self.drag_start = None
        self.draw()

    def draw_preview(self, x, y):
        self.draw()
        if self.tool == "member" and self.member_first is not None:
            x1, y1 = self.nodes[self.member_first]
            self.canvas.create_line(x1, y1, x, y, fill="#89b4fa", width=2, dash=(4, 4))

    def solve(self):
        if len(self.nodes) == 0:
            messagebox.showinfo("Solve", "Add nodes and members first.")
            return
        self.member_forces, self.reactions, self.solved = solve_truss(
            self.nodes, self.members, self.supports, self.loads
        )
        self.draw()
        if self.solved:
            self.status.config(text="Solved | Tension=red, Compression=blue")
        else:
            err = getattr(solve_truss, "last_error", None)
            self.status.config(text=err or "Cannot solve")

    def draw(self):
        self.canvas.delete("all")

        if not self.nodes:
            self.canvas.create_text(
                self.canvas_width // 2, self.canvas_height // 2,
                text="Node tool: click to add nodes\nThen Member: drag between nodes to connect",
                font=("Consolas", 14), fill="#6c7086", justify=tk.CENTER
            )
            return

        max_f = 1.0
        if self.solved and self.member_forces is not None:
            max_f = max(abs(f) for f in self.member_forces) or 1

        for m_idx, (i, j) in enumerate(self.members):
            x1, y1 = self.nodes[i]
            x2, y2 = self.nodes[j]
            if self.solved and self.member_forces is not None:
                f = self.member_forces[m_idx]
                w = max(1, min(6, 1 + 4 * abs(f) / max_f))
                color = "#f38ba8" if f > 0 else "#89b4fa"
                self.canvas.create_line(x1, y1, x2, y2, fill=color, width=int(w), capstyle=tk.ROUND)
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                self.canvas.create_text(mx, my - 10, text=f"{f:.1f}", font=("Consolas", 9), fill="#cdd6f4")
            else:
                self.canvas.create_line(x1, y1, x2, y2, fill="#6c7086", width=2)

        for i, (x, y) in enumerate(self.nodes):
            r = 8
            fill = "#a6e3a1" if i in self.supports else "#f9e2af"
            if self.member_first == i:
                fill = "#89b4fa"
            self.canvas.create_oval(x - r, y - r, x + r, y + r, fill=fill, outline="#45475a", width=2)
            self.canvas.create_text(x, y + 20, text=str(i), font=("Consolas", 9), fill="#cdd6f4")

        # Loads
        for node_idx, (Fx, Fy) in self.loads.items():
            if node_idx >= len(self.nodes):
                continue
            cx, cy = self.nodes[node_idx]
            mag = math.hypot(Fx, Fy)
            if mag < 1e-6:
                continue
            ax = Fx / mag * 35
            ay = Fy / mag * 35
            self.canvas.create_line(cx, cy, cx + ax, cy + ay, fill="#f38ba8", width=3, arrow=tk.LAST)
            self.canvas.create_text(cx + ax * 1.3, cy + ay * 1.3, text=f"({Fx:.0f},{Fy:.0f})",
                                   font=("Consolas", 8), fill="#f38ba8")

        # Moments
        for node_idx, M in self.moments.items():
            if node_idx >= len(self.nodes):
                continue
            cx, cy = self.nodes[node_idx]
            self.canvas.create_oval(cx - 18, cy - 18, cx + 18, cy + 18, outline="#cba6f7", width=2)
            self.canvas.create_text(cx + 25, cy, text=f"M={M:.0f}", font=("Consolas", 9), fill="#cba6f7")

        # Supports
        for node_idx, supp_type in self.supports.items():
            if node_idx >= len(self.nodes):
                continue
            cx, cy = self.nodes[node_idx]
            if supp_type == 'pin':
                self.canvas.create_line(cx, cy, cx, cy + 28, fill="#6c7086", width=2)
                self.canvas.create_polygon(cx - 12, cy + 28, cx + 12, cy + 28, cx, cy + 40, fill="#6c7086")
            elif supp_type == 'roller_x':
                self.canvas.create_line(cx, cy, cx, cy + 28, fill="#6c7086", width=2)
                self.canvas.create_oval(cx - 10, cy + 22, cx + 10, cy + 34, outline="#6c7086", width=2)

        # Reactions
        if self.solved and self.reactions:
            for node_idx, comps in self.reactions.items():
                if node_idx >= len(self.nodes):
                    continue
                cx, cy = self.nodes[node_idx]
                rx = comps.get('Rx', 0)
                ry = comps.get('Ry', 0)
                if abs(rx) > 0.1:
                    dx = 1 if rx > 0 else -1
                    self.canvas.create_line(cx, cy, cx + dx * 30, cy, fill="#89b4fa", width=2, arrow=tk.LAST)
                    self.canvas.create_text(cx + dx * 40, cy, text=f"Rx={rx:.1f}", font=("Consolas", 8), fill="#89b4fa")
                if abs(ry) > 0.1:
                    dy = 1 if ry > 0 else -1
                    self.canvas.create_line(cx, cy, cx, cy + dy * 30, fill="#89b4fa", width=2, arrow=tk.LAST)
                    self.canvas.create_text(cx + 15, cy + dy * 40, text=f"Ry={ry:.1f}", font=("Consolas", 8), fill="#89b4fa")


def main():
    root = tk.Tk()
    StaticsEditor(root)
    root.mainloop()


if __name__ == "__main__":
    main()
