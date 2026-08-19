Supongamos que $f$ es integrable en el sentido de Tao. Sea $P^\square$ tal que

$$
U(P^\square,f)-L(P^\square,f)<\varepsilon.
$$

Para cada $x_i$, si

$$
\alpha(x_i)-\alpha(x_i^-)>0,
$$

tomamos $y_i<x_i$, $y_i\leadsto x_i$. Entonces

$$
\inf_{[y_i,x_i]}f,\ \sup_{[y_i,x_i]}f
\leadsto f(x_i)
$$

por continuidad por la izquierda. Análogamente, si

$$
\alpha(x_i^+)-\alpha(x_i)>0,
$$

tomamos $z_i>x_i$, $z_i\leadsto x_i$, y

$$
\inf_{[x_i,z_i]}f,\ \sup_{[x_i,z_i]}f
\leadsto f(x_i).
$$

Así,

\begin{align}
\Delta\alpha_i^-
&=\alpha(x_i)-\alpha(y_i)
\leadsto
\alpha(x_i)-\alpha(x_i^-),\\
\Delta\alpha_i^+
&=\alpha(z_i)-\alpha(x_i)
\leadsto
\alpha(x_i^+)-\alpha(x_i).
\end{align}

Por tanto,

\begin{align}
m_i^-\Delta\alpha_i^-
&\leadsto
f(x_i)\bigl[\alpha(x_i)-\alpha(x_i^-)\bigr],\\
m_i^+\Delta\alpha_i^+
&\leadsto
f(x_i)\bigl[\alpha(x_i^+)-\alpha(x_i)\bigr],
\end{align}

y, si ambos son positivos,

$$
m_i^-\Delta\alpha_i^-+
m_i^+\Delta\alpha_i^+
\leadsto
f(x_i)\alpha(\{x_i\}).
$$

Para los intervalos restantes,

$$
\inf_{[z_{i-1},y_i]}f
\bigl(\alpha(y_i)-\alpha(z_{i-1})\bigr)
\leadsto
m_{H_i}\alpha((x_{i-1},x_i)),
$$

y análogamente para los supremos.

Construimos así una división clásica $P'_\delta$ tal que

\begin{align}
\lim_{\delta\downarrow0}L(P'_\delta,f)
&=L(P^\square,f),\\
\lim_{\delta\downarrow0}U(P'_\delta,f)
&=U(P^\square,f).
\end{align}

Como $P'_\delta$ es una división clásica,

$$
L(P'_\delta,f)\leq I_\delta\leq U(P'_\delta,f),
$$

donde $I_\delta$ es cualquier suma de Riemann–Stieltjes asociada a $P'_\delta$.

Más directamente, si definimos

$$
I^-=\sup_P L(P,f),
\qquad
I^+=\inf_P U(P,f),
$$

entonces, para todo $\delta$,

$$
L(P'_\delta,f)\leq I^+\leq I^- \leq U(P'_\delta,f).
$$

Tomando $\delta\downarrow0$,

$$
L(P^\square,f)\leq I^+\leq I^-\leq U(P^\square,f).
$$

Por lo tanto,

$$
I^+-I^-
\leq
U(P^\square,f)-L(P^\square,f)
<\varepsilon.
$$

Como $\varepsilon>0$ es arbitrario,

$$
I^+=I^-.
$$

Luego $f\in\mathscr R_\alpha([a,b])$ y las integrales coinciden.