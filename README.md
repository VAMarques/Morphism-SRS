# Morphism SRS ⚡

**Morphism SRS** is a modern, cross-platform Spaced Repetition System designed specifically for **Mathematics, Logic, and Proof Sequences**. It combines graph-based knowledge mapping, FSRS retention algorithms, offline MathJax 3 LaTeX rendering, and partial retention sequence modeling.

---

## 🌟 Key Features

- **Graph Explorer**: Visualize courses as interactive directed acyclic graphs (DAGs) of prerequisite concepts and notes.
- **FSRS-Powered Scheduling**: State-of-the-art Free Spaced Repetition Scheduler (FSRS 4.5/5) memory decay modeling.
- **Partial Retention Joint Probability Model**: Evaluates joint retention $P(\bigcap A_i) = \prod R_i(t) \le \text{desired\_retention}$ across prerequisite nodes to optimize review sessions.
- **100% Offline MathJax 3 LaTeX Rendering**: Renders beautiful TeX formulas (`$...$`, `$$...$$`, `\(...\)`, `\[...\]`) completely offline.
- **Proof Sequences & Intraday Reviews**: Supports single-step and full-sequence proof step reviews with intraday interval tracking.
- **Retrievability Info Plotter**: Interactive Chart.js retrievability decay curves ($R(t)$) with multi-scale zoom (24 Hours, 48 Hours, 7 Days, 30 Days, 90 Days).
- **Cross-Platform**: Runs natively on **Windows**, **macOS (Darwin)**, and **Linux**.

---

## 🚀 Quick Start & Setup

### 🐧 Linux & 🍎 macOS (Darwin)

Run the automated setup launcher:

```bash
chmod +x setup.sh
./setup.sh
```

`setup.sh` automatically creates a Python virtual environment (`.venv`), installs all required dependencies from `requirements.txt`, and launches the application.

---

### 🪟 Windows

1. Open PowerShell or Command Prompt in the project folder.
2. Create and activate a virtual environment:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
3. Install dependencies:
   ```powershell
   pip install -r requirements.txt
   ```
4. Run Morphism SRS:
   ```powershell
   python main.py
   ```

---

## ⌨️ Keyboard Shortcuts (Review Mode)

| Shortcut | Action |
| :--- | :--- |
| **Space** | Reveal Answer (Front) / Rate **Good** (Back) |
| **1** | Rate **Again** |
| **2** | Rate **Hard** |
| **3** | Rate **Good** |
| **4** | Rate **Easy** |
| **Ctrl + Return** | Insert `<br>` line break in editor |

---

## 📄 License

Distributed under the **MIT License**. See `LICENSE` for more information.
