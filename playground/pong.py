"""
Solo Pong - A classic pong game with tkinter
Play against an AI paddle or survive as long as you can!
"""

import tkinter as tk
import random
import math


class PongGame:
    def __init__(self, root):
        self.root = root
        self.root.title("Solo Pong")
        self.root.resizable(False, False)

        # Game dimensions
        self.width = 600
        self.height = 400
        self.paddle_width = 100
        self.paddle_height = 12
        self.ball_radius = 8
        self.ball_speed = 5  # Constant magnitude of velocity vector

        # Game state
        self.score = 0
        self.game_over = False
        self.paused = False

        # Canvas
        self.canvas = tk.Canvas(
            root, width=self.width, height=self.height,
            bg="#1a1a2e", highlightthickness=0
        )
        self.canvas.pack(pady=10)

        # Score label
        self.score_label = tk.Label(
            root, text="Score: 0", font=("Consolas", 16),
            fg="#eee", bg="#16213e"
        )
        self.score_label.pack(pady=5)

        # Instructions
        self.inst_label = tk.Label(
            root, text="Mouse to move | SPACE to pause | R to restart",
            font=("Consolas", 10), fg="#888", bg="#16213e"
        )
        self.inst_label.pack()

        root.configure(bg="#16213e")

        self.mouse_x = self.width // 2  # Track mouse for paddle
        self.game_over_text_ids = []  # For removing on restart

        # Paddle positions (player bottom, AI top)
        self.player_x = self.width // 2 - self.paddle_width // 2
        self.ai_x = self.width // 2 - self.paddle_width // 2
        self.paddle_y_offset = 30

        # Ball
        self.ball_x = self.width // 2
        self.ball_y = self.height // 2
        angle = random.uniform(-0.8, 0.8)
        self.ball_dx = self.ball_speed * math.cos(angle)
        self.ball_dy = -self.ball_speed * math.sin(angle)  # Start going up

        # Create game objects
        self.player_paddle = self.canvas.create_rectangle(
            self.player_x, self.height - self.paddle_y_offset,
            self.player_x + self.paddle_width, self.height - self.paddle_y_offset + self.paddle_height,
            fill="#e94560", outline="#eee", width=1
        )
        self.ai_paddle = self.canvas.create_rectangle(
            self.ai_x, self.paddle_y_offset - self.paddle_height,
            self.ai_x + self.paddle_width, self.paddle_y_offset,
            fill="#0f3460", outline="#eee", width=1
        )
        self.ball = self.canvas.create_oval(
            self.ball_x - self.ball_radius, self.ball_y - self.ball_radius,
            self.ball_x + self.ball_radius, self.ball_y + self.ball_radius,
            fill="#e94560", outline="#eee", width=1
        )

        # Bind mouse and keys (root Motion so paddle follows even over labels)
        self.root.bind("<Motion>", self.on_mouse_move)
        self.root.bind("<space>", self.toggle_pause)
        self.root.bind("r", self.restart)
        self.root.bind("R", self.restart)
        self.root.focus_set()

        self.game_loop()

    def on_mouse_move(self, event):
        # Convert to canvas x (event is relative to root)
        cx = event.x - self.canvas.winfo_x()
        self.mouse_x = max(0, min(self.width, cx))

    def toggle_pause(self, event=None):
        if not self.game_over:
            self.paused = not self.paused

    def update_player(self):
        # Center paddle on mouse
        self.player_x = self.mouse_x - self.paddle_width // 2
        self.player_x = max(0, min(self.width - self.paddle_width, self.player_x))
        self.canvas.coords(
            self.player_paddle,
            self.player_x, self.height - self.paddle_y_offset,
            self.player_x + self.paddle_width,
            self.height - self.paddle_y_offset + self.paddle_height
        )

    def update_ai(self):
        # AI tracks ball with some imperfection
        target = self.ball_x - self.paddle_width // 2
        target = max(0, min(self.width - self.paddle_width, target))
        diff = target - self.ai_x
        # Add slight delay/imprecision
        move = max(-8, min(8, diff * 0.15))
        self.ai_x += move
        self.ai_x = max(0, min(self.width - self.paddle_width, self.ai_x))
        self.canvas.coords(
            self.ai_paddle,
            self.ai_x, self.paddle_y_offset - self.paddle_height,
            self.ai_x + self.paddle_width, self.paddle_y_offset
        )

    def normalize_ball_speed(self):
        """Scale velocity so magnitude always equals ball_speed."""
        speed = math.hypot(self.ball_dx, self.ball_dy)
        if speed > 0:
            scale = self.ball_speed / speed
            self.ball_dx *= scale
            self.ball_dy *= scale

    def update_ball(self):
        self.ball_x += self.ball_dx
        self.ball_y += self.ball_dy

        # Left/right walls
        if self.ball_x - self.ball_radius <= 0:
            self.ball_x = self.ball_radius
            self.ball_dx = -self.ball_dx
            self.normalize_ball_speed()
        if self.ball_x + self.ball_radius >= self.width:
            self.ball_x = self.width - self.ball_radius
            self.ball_dx = -self.ball_dx
            self.normalize_ball_speed()

        # AI paddle (top) - player scores!
        ai_paddle_bottom = self.paddle_y_offset
        if self.ball_dy < 0 and self.ball_y - self.ball_radius <= ai_paddle_bottom:
            ball_left = self.ball_x - self.ball_radius
            ball_right = self.ball_x + self.ball_radius
            if ball_right >= self.ai_x and ball_left <= self.ai_x + self.paddle_width:
                self.ball_y = ai_paddle_bottom + self.ball_radius
                self.ball_dy = -self.ball_dy
                # Curved paddle: flat center (0 deflection), angled toward edges
                hit_pos = (self.ball_x - self.ai_x) / self.paddle_width - 0.5  # -0.5 to 0.5
                self.ball_dx = self.ball_dx * (0.2 + 1.6 * abs(hit_pos)) + (hit_pos ** 3) * 16
                self.normalize_ball_speed()
                self.score += 1
                self.score_label.config(text=f"Score: {self.score}")

        # Player paddle (bottom) - must hit or game over
        # Use ball edges for overlap (ball has radius - center check misses edge hits)
        paddle_top = self.height - self.paddle_y_offset - self.paddle_height
        if self.ball_dy > 0 and self.ball_y + self.ball_radius >= paddle_top:
            ball_left = self.ball_x - self.ball_radius
            ball_right = self.ball_x + self.ball_radius
            paddle_left = self.player_x
            paddle_right = self.player_x + self.paddle_width
            # Overlap: ball overlaps paddle horizontally
            if ball_right >= paddle_left and ball_left <= paddle_right:
                self.ball_y = paddle_top - self.ball_radius
                self.ball_dy = -self.ball_dy
                # Curved paddle: flat center (0 deflection), angled toward edges
                hit_pos = (self.ball_x - self.player_x) / self.paddle_width - 0.5  # -0.5 to 0.5
                self.ball_dx = self.ball_dx * (0.2 + 1.6 * abs(hit_pos)) + (hit_pos ** 3) * 16
                self.normalize_ball_speed()
            else:
                self.end_game()

        self.canvas.coords(
            self.ball,
            self.ball_x - self.ball_radius, self.ball_y - self.ball_radius,
            self.ball_x + self.ball_radius, self.ball_y + self.ball_radius
        )

    def end_game(self):
        self.game_over = True
        self.game_over_text_ids.append(self.canvas.create_text(
            self.width // 2, self.height // 2,
            text=f"GAME OVER\nScore: {self.score}",
            font=("Consolas", 28), fill="#e94560",
            justify="center"
        ))
        self.game_over_text_ids.append(self.canvas.create_text(
            self.width // 2, self.height // 2 + 60,
            text="Press R to restart",
            font=("Consolas", 12), fill="#888"
        ))

    def restart(self, event=None):
        if not self.game_over:
            return
        # Remove game over text
        for tid in self.game_over_text_ids:
            self.canvas.delete(tid)
        self.game_over_text_ids.clear()
        # Reset state
        self.game_over = False
        self.paused = False
        self.score = 0
        self.score_label.config(text="Score: 0")
        self.player_x = self.width // 2 - self.paddle_width // 2
        self.ai_x = self.width // 2 - self.paddle_width // 2
        self.ball_x = self.width // 2
        self.ball_y = self.height // 2
        angle = random.uniform(-0.8, 0.8)
        self.ball_dx = self.ball_speed * math.cos(angle)
        self.ball_dy = -self.ball_speed * math.sin(angle)

    def game_loop(self):
        if not self.game_over and not self.paused:
            self.update_player()
            self.update_ai()
            self.update_ball()
        self.root.after(16, self.game_loop)  # ~60 FPS


def main():
    root = tk.Tk()
    game = PongGame(root)
    root.mainloop()


if __name__ == "__main__":
    main()
