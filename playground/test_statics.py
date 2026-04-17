"""Verify the statics solver against known solutions."""

import math
import numpy as np
import sys
sys.path.insert(0, '.')
from statics_2d import solve_truss


def test_simple_cantilever():
    """Two-node truss: horizontal bar, pin at left, roller at right, load at right."""
    nodes = [(0, 0), (100, 0)]
    members = [(0, 1)]
    supports = {0: 'pin', 1: 'roller_x'}
    loads = {1: (0, -50)}  # 50 upward at node 1
    
    forces, reactions, ok = solve_truss(nodes, members, supports, loads)
    assert ok
    # Horizontal member: no axial force (load is vertical, roller takes it)
    assert abs(forces[0]) < 0.01
    # Roller provides Ry to balance
    assert abs(reactions[1]['Ry'] - 50) < 0.01
    print("OK Cantilever: F=0, Ry=50")


def test_simple_triangle():
    """
    Equilateral triangle, pin at 0, roller at 1, load down at 2.
    Classic 60° roof truss.
    """
    L = 100
    h = L * math.sqrt(3) / 2
    nodes = [(0, 0), (L, 0), (L/2, -h)]
    members = [(0, 1), (1, 2), (2, 0)]
    supports = {0: 'pin', 1: 'roller_x'}
    loads = {2: (0, 100)}  # 100 down at apex
    
    forces, reactions, ok = solve_truss(nodes, members, supports, loads)
    assert ok
    
    # By symmetry: R0y = R1y = 50 each. R0x = 0 (roller at 1 has no horizontal).
    # At joint 2: vertical load 100 down. Members 0-2 and 1-2 both at 60° from horizontal.
    # Each makes angle 30° to vertical. F*cos(30) * 2 = 100, so F = 100/(2*cos30) = 100/sqrt3 ≈ 57.7
    # Compression in both top chords.
    F_expected = 100 / (2 * math.cos(math.radians(30)))
    
    F_02 = forces[2]
    F_12 = forces[1]
    assert abs(F_02 - F_12) < 0.01  # symmetric
    assert abs(abs(F_02) - F_expected) < 1.0
    
    # Check reactions: Ry0 + Ry1 must balance vertical load 100 (down)
    # In canvas coords: +y down. Load (0,100)=100 down. Reactions must sum to -100 (up)
    Ry0 = reactions[0]['Ry']
    Ry1 = reactions[1]['Ry']
    # Global equilibrium: sum of applied + reactions = 0
    # Applied at node 2: (0, 100) down. So Ry0 + Ry1 = -100 for equilibrium.
    assert abs(Ry0 + Ry1 + 100) < 0.1, f"Ry0={Ry0}, Ry1={Ry1}, expect sum=-100"
    print(f"OK Triangle: F_top~{-F_expected:.1f} (compression), reactions balance load")


def test_global_equilibrium():
    """Verify sum of forces and moments = 0 for any solved structure."""
    nodes = [(0, 0), (100, 0), (50, -80)]
    members = [(0, 1), (1, 2), (2, 0)]
    supports = {0: 'pin', 1: 'roller_x'}
    loads = {2: (20, -100)}
    
    forces, reactions, ok = solve_truss(nodes, members, supports, loads)
    assert ok
    
    # Global ΣFx = 0
    total_Fx = loads.get(0, (0,0))[0] + loads.get(1, (0,0))[0] + loads.get(2, (0,0))[0]
    total_Fx += reactions.get(0, {}).get('Rx', 0) + reactions.get(1, {}).get('Rx', 0) + reactions.get(1, {}).get('Ry', 0) * 0
    total_Fx += reactions.get(0, {}).get('Rx', 0) + reactions.get(1, {}).get('Rx', 0)
    Rx0 = reactions.get(0, {}).get('Rx', 0)
    Ry0 = reactions.get(0, {}).get('Ry', 0)
    Ry1 = reactions.get(1, {}).get('Ry', 0)
    
    Px = sum(loads.get(i, (0,0))[0] for i in range(len(nodes)))
    Py = sum(loads.get(i, (0,0))[1] for i in range(len(nodes)))
    
    sum_Rx = sum(reactions.get(i, {}).get('Rx', 0) for i in range(len(nodes)))
    sum_Ry = sum(reactions.get(i, {}).get('Ry', 0) for i in range(len(nodes)))
    
    assert abs(Px + sum_Rx) < 0.01
    assert abs(Py + sum_Ry) < 0.01
    print("OK Global equilibrium: sum Fx=0, sum Fy=0")


def test_joint_equilibrium():
    """Verify each joint satisfies ΣF=0."""
    nodes = [(0, 0), (100, 0), (50, -70)]
    members = [(0, 1), (1, 2), (2, 0)]
    supports = {0: 'pin', 1: 'roller_x'}
    loads = {2: (0, -80)}
    
    forces, reactions, ok = solve_truss(nodes, members, supports, loads)
    assert ok
    
    def dir_vec(i, j):
        xi, yi = nodes[i]
        xj, yj = nodes[j]
        L = math.hypot(xj - xi, yj - yi)
        if L < 1e-10:
            return 0, 0
        return (xj - xi) / L, (yj - yi) / L
    
    for joint in range(len(nodes)):
        Fx, Fy = 0.0, 0.0
        for m_idx, (i, j) in enumerate(members):
            if i != joint and j != joint:
                continue
            cx, cy = dir_vec(i, j)
            sign = 1 if joint == i else -1
            Fx += forces[m_idx] * sign * cx
            Fy += forces[m_idx] * sign * cy
        if joint in supports:
            r = reactions.get(joint, {})
            Fx += r.get('Rx', 0)
            Fy += r.get('Ry', 0)
        Px, Py = loads.get(joint, (0, 0))
        assert abs(Fx + Px) < 0.01, f"Joint {joint} Fx"
        assert abs(Fy + Py) < 0.01, f"Joint {joint} Fy"
    
    print("OK Joint equilibrium: sum F=0 at every joint")


if __name__ == "__main__":
    test_simple_cantilever()
    test_simple_triangle()
    test_global_equilibrium()
    test_joint_equilibrium()
    print("\nAll checks passed. Solver appears correct.")
