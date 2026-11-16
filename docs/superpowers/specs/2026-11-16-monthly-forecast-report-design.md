# Informe mensual de pre-booking con forecast P10/P50/P90

Aprobado por Pablo el 2026-11-16.

## Intención
Cada mes, cruzar (a) el historial de envíos de los últimos 3 años, (b) la actividad reciente y (c) las salidas disponibles por
ruta, para recomendar qué buques pre-reservar sin quedar con bookings sin usar, a fechas más baratas y más cercanas. Mejora
margen, operación y atención al cliente. Sale por correo con un PDF adjunto.

## Metas
- Forecast de contenedores por ruta (puerto de salida y llegada) para el mes siguiente, con P10, P50 y P90.
- Recomendaciones en tres niveles: **comprar** (hasta P10), **preparar** (P10 a P50), **vigilar** (P50 a P90).
- Correo con PDF por Resend. Los números los calcula código determinista; Claude solo redacta el resumen.

## No metas
- Reservar de verdad (el booking sigue simulado). Dependencias de ML pesadas. Scheduler en producción (primero un comando).
- Modelar clientes individuales o márgenes reales: se estima ahorro de precio frente a la ventana de fechas.

## Anti-metas
- Recomendar comprar más de lo que el historial respalda. P10 se define para que el riesgo de no usarlo sea ~10 %.

## Interpretaciones acordadas
- P10 = volumen que se supera el 90 % de las veces → reservar. P50 = preparar opciones sin comprar. P90 = vigilar.
- Horizonte por defecto: el mes calendario siguiente; configurable hasta 6 meses (la BD de salidas simuladas llega a 6).

## Enfoques considerados
1. **Python puro: estacional del mismo mes de años previos × factor de crecimiento reciente, cuantiles de errores validados
   dejando un año fuera.** Elegido: cero dependencias, milisegundos, explicable, replica lo que Pablo describe.
2. Regresión cuantil con scikit-learn / ETS con statsmodels: con 36 puntos por ruta se sobreajusta y añade dependencias pesadas.
3. Boosting (LightGBM): desproporcionado para este volumen de datos.

## Diseño
- `history/mockdb.py`: SQLite `artifacts/mock_history.sqlite`, 36 meses de envíos por ruta (misma lista de rutas que
  `carriers/mockdb.py`), con temporada alta en diciembre, caída en año nuevo chino, tendencia y ruido; determinista.
- `forecast/model.py` (Python puro): para una ruta y un mes objetivo, línea base = promedio del mismo mes en años previos;
  factor de crecimiento = actividad de los últimos 3 meses / mismos 3 meses de años previos; cuantiles de la razón real/pronóstico
  obtenida validando cada año histórico con los demás. Devuelve P10, P50, P90 y una métrica de error frente a un pronóstico ingenuo.
- `forecast/plan.py`: reparte P10 / (P50-P10) / (P90-P50) entre las salidas del mes en la BD de salidas, por ruta; prefiere
  precio bajo y fecha cercana, respeta TEU libres y limita la participación por salida para repartir riesgo.
- `report/pdf.py` (fpdf2): portada con resumen, tabla por nivel, detalle por ruta con histórico vs pronóstico, supuestos.
- `report/narrative.py`: resumen en español con Claude a partir de los números estructurados; plantilla fija si no hay clave.
- `report/monthly.py`: orquesta y envía por Resend (`email.send_message` con adjunto). Comando: `uv run python -m form_agent.report.monthly`.

## Para quien construye
Decidir tamaños de reparto y umbrales (por defecto: máximo 50 % de una ruta en una sola salida) y el diseño visual del PDF.
Probar el modelo con backtest: debe superar al pronóstico ingenuo y cubrir ~80 % de los casos entre P10 y P90.
