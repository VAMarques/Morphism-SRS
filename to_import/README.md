# Morphism SRS — Bulk Import Guide (`to_import/`)

Place `.mdsl` (Morphism DSL) or `.json` deck files in this folder to import them directly into your courses. This guide is designed both for human authors and as a system prompt / reference for **bulk AI note generation**.

---

## 1. Core Principles for Designing Good Mathematical Notes

### 1.1 Separate Statements from Proofs
- **Never combine a theorem statement and a multi-step proof into the same Note.**
- Create one **Statement Note** (`MODE standard` or `MODE cloze`) that tests the definition, intuition, hypotheses, and conclusion of the theorem.
- Create a separate **Proof Note** (`MODE serial`) that breaks the proof into logical steps, and link them in the DAG:
  ```text
  LINK "Theorem Statement Note" -> "Proof of Theorem Note"
  ```

### 1.2 Choosing the Right Review Mode (`MODE`)
Morphism SRS Prototype 2 supports three mathematical conditioning modes at the Note level:

1. **`MODE standard` — Independent Cards ($P(A_i)$) [Rounded Rectangle]**
   - Each card in the note is scheduled and reviewed independently without showing sibling cards.
   - **Best for**: Definitions, Theorem Statements, Examples, Counterexamples, and Conceptual Questions.
   - **Multi-card Standard Notes**: A single concept should often have 2–4 independent cards inside the same `standard` note:
     - *Card 1 (Formal Statement)*: "State the formal definition of X."
     - *Card 2 (Intuition / Motivation)*: "What is the geometric or algebraic intuition behind X?"
     - *Card 3 (Counterexample / Edge Case)*: "Why does hypothesis H matter in X? Give a counterexample when H fails."

2. **`MODE serial` — Proof Chains ($P(A_i \mid A_j, j < i)$) [Diamond]**
   - Cards represent ordered logical steps $A_1, A_2, \dots, A_n$ of a mathematical proof or derivation.
   - Each step $A_i$ has its own independent FSRS v5 schedule (so you repeat the hard bottleneck step $A_k$ more often without wasting time on trivial steps), **and** when reviewing step $A_i$, steps $A_1, \dots, A_{i-1}$ are automatically displayed above it as verified context!
   - **Best for**: Multi-step proofs, derivations, and algorithms.

3. **`MODE cloze` — Mutual Context ($P(A_i \mid A_j, j \neq i)$) [Ellipse]**
   - When reviewing card $A_i$, **all other sibling cards** ($A_j$ for $j \neq i$) are displayed as given context (before and after $A_i$), and the user must supply the missing piece $A_i$.
   - **Best for**: Equivalence theorems ("TFAE: (1) ... (2) ... (3) ..."), commutative diagram properties, or axioms of a structure where each card tests one axiom given the others.

---

## 2. The Morphism DSL (`.mdsl`) Specification

### 2.1 Keywords
- `COURSE "Course Name"` — Target course name (optional if importing into an currently selected course).
- `FOLDER "Category/Subcategory"` — Optional folder hierarchy path.
- `NEW NOTE "Note Title"` — Starts a new mathematical note node in the DAG.
- `MODE standard | serial | cloze` — Sets the review conditioning mode and node shape.
- `TAGS tag_one, tag_two` — Comma-separated standardized snake_case tags (from `tags_default.csv`).
- `RETENTION 0.80` — Optional target FSRS retention in $[0.70, 0.99]$.
- `CARD 1 "Card Title"` — Starts a card/step inside the current note.
- `FRONT` — Begins the multiline HTML/LaTeX question prompt.
- `BACK` — Begins the multiline HTML/LaTeX answer.
- `LINK "Prerequisite Note Title" -> "Dependent Note Title"` — Creates a directed prerequisite edge in the DAG. (`LINK "Prerequisite Note Title" "Dependent Note Title"` is also supported.)

### 2.2 Built-In LaTeX Macros
The following macros are preloaded offline in MathJax and can be used in any card:
- Blackboard bold: `\RR`, `\CC`, `\NN`, `\ZZ`, `\QQ`
- Delimiters: `\norm{x}`, `\abs{x}`, `\parens{x}`, `\inner{x}{y}`
- Colored Greek letters: `\ph`, `\ps`, `\ch`, `\ta`, `\gm`, `\al`, `\be`, `\eps`
- Logic & Calculus: `\lthen` ($\Rightarrow$), `\liff` ($\Leftrightarrow$), `\lxor` ($\veebar$), `\True`, `\False`, `\d` (differential $\mathrm{d}$)

---

## 3. Complete `.mdsl` Example (`test.mdsl`)

```text
# Example Morphism SRS Deck (.mdsl)
COURSE "Group Theory Foundations"
FOLDER "Pure Mathematics/Algebra"

NEW NOTE "Definition of a Group"
MODE standard
TAGS group_theory, definition, binary_operation

CARD 1 "Formal Axiom Definition"
FRONT
What is the formal definition of a <b>group</b> $(G, \cdot)$?
BACK
A set $G$ equipped with a binary operation $\cdot : G \times G \to G$ satisfying:
<ul>
  <li><b>Associativity:</b> $(a \cdot b) \cdot c = a \cdot (b \cdot c)$ for all $a, b, c \in G$.</li>
  <li><b>Identity:</b> There exists $e \in G$ such that $e \cdot a = a \cdot e = a$ for all $a \in G$.</li>
  <li><b>Inverses:</b> For each $a \in G$, there exists $a^{-1} \in G$ such that $a \cdot a^{-1} = a^{-1} \cdot a = e$.</li>
</ul>

CARD 2 "Non-Example"
FRONT
Why is $(\ZZ, -)$ <i>not</i> a group?
BACK
Subtraction on $\ZZ$ fails <b>associativity</b>: $(1 - 1) - 1 = -1 \neq 1 - (1 - 1) = 1$.

NEW NOTE "Uniqueness of the Group Identity"
MODE serial
TAGS group_theory, proof, uniqueness

CARD 1 "Step 1: Setup Two Candidate Identities"
FRONT
Suppose $e$ and $e'$ are both identity elements in a group $(G, \cdot)$. How do we relate them?
BACK
We evaluate the product $e \cdot e'$ in two different ways using the identity axiom.

CARD 2 "Step 2: Two-Way Evaluation"
FRONT
Evaluate $e \cdot e'$ using first that $e$ is a left identity, and second that $e'$ is a right identity.
BACK
Since $e$ is a left identity, $e \cdot e' = e'$.<br>
Since $e'$ is a right identity, $e \cdot e' = e$.<br>
Therefore, $e = e'$. $\blacksquare$

LINK "Definition of a Group" -> "Uniqueness of the Group Identity"
```
