"use client";

import styles from "./OptimizationObjectiveSelector.module.css";

export type OptimizationObjectiveOption = {
  id: string;
  label: string;
};

export default function OptimizationObjectiveSelector({
  options,
  selectedObjectiveIds,
  customObjective,
  onToggleObjective,
  onCustomObjectiveChange,
}: {
  options: readonly OptimizationObjectiveOption[];
  selectedObjectiveIds: string[];
  customObjective: string;
  onToggleObjective: (objectiveId: string) => void;
  onCustomObjectiveChange: (customObjective: string) => void;
}) {
  const selected = new Set(selectedObjectiveIds);
  const showNudge = selectedObjectiveIds.length === 0 && customObjective.trim().length === 0;

  return (
    <div className={styles.selector}>
      <div className={styles.grid} aria-label="Scan optimization objectives">
        {options.map((option) => {
          const isSelected = selected.has(option.id);
          return (
            <button
              key={option.id}
              type="button"
              className={`${styles.chip} ${isSelected ? styles.selected : ""}`}
              aria-pressed={isSelected}
              onClick={() => onToggleObjective(option.id)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
      {showNudge && (
        <p className={styles.nudge}>
          Tip: selecting at least one objective helps AISO prioritize your question bank.
        </p>
      )}
      <label className={styles.customField}>
        <span>Optional: add a custom objective</span>
        <textarea
          className={styles.textarea}
          value={customObjective}
          onChange={(event) => onCustomObjectiveChange(event.target.value)}
          placeholder="Optional custom objective"
          rows={2}
          maxLength={500}
        />
      </label>
    </div>
  );
}
