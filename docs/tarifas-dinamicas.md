# Tarifas dinámicas: guía para administración

> Guía histórica del mecanismo temporal de Fase 1.5. **No editar estos JSON para
> cambiar tarifas en producción.** La fuente vigente es la base comercial y sus
> endpoints administrativos. Ver [operación de Fase 1.6](fase-16.md).

Cada programa tiene un único archivo comercial `*.pricing.json`, junto a su
Markdown en `backend/knowledge/02_carreras` o `03_cursos_cortos`. Los Markdown
contienen información académica y un enlace comercial; no copies importes allí.
El índice ChromaDB puede conservar información antigua: los precios efectivos
se leen directamente de estos JSON por PricingService.

Se eligió JSON asociado por su validación estricta y porque no requiere nuevas
dependencias ni cambios en la ingestión vectorial. Front matter YAML reúne todo
en un documento, pero mezclaría campañas y metadatos académicos en el cargador
actual. YAML asociado es legible, pero añade reglas de indentación y conversión
de fechas. JSON evita esas conversiones; su desventaja es que no acepta comentarios
y requiere comillas y comas correctas. Usa `observations` para comentarios.

## Estado inicial

La campaña `confirmacion_inicial` guarda la inscripción confirmada de S/ 80
en cada programa. No tiene fechas comerciales inventadas: `starts_on` y
`ends_on` son `null`, y aplica hasta que el administrador cambie o delimite
la campaña. Todas las demás tarifas son `pending` con `amount: null`.
Los importes de los Markdown anteriores NO han sido activados ni deducidos.
El historial Git conserva esas tablas para revisión y confirmación posterior.

## Cómo editar

1. Edita el JSON del programa. `program`, `program_label`, `aliases`,
   `modalities` y `shifts` identifican el programa y las variantes permitidas.
2. En `prices`, modifica o agrega la fila del concepto y variante necesarios.
3. Valida antes de publicar desde la raíz del proyecto:

   ```powershell
   & backend/venv/Scripts/python.exe -B backend/validate_pricing.py
   ```

4. Guarda el archivo completo. Preferentemente escribe una copia y reemplaza
   el original de forma atómica. La siguiente consulta observa el cambio:
   no hay reinicio del backend, compilación del frontend ni reindexación.

Ejemplo de **estructura**, con el importe de inscripción inicialmente confirmado:

```json
{
  "concept": "inscripcion",
  "modality": null,
  "shift": null,
  "amount": "80.00",
  "currency": "PEN",
  "status": "active",
  "campaign": "confirmacion_inicial",
  "starts_on": null,
  "ends_on": null,
  "promotions": [],
  "observations": "Tarifa confirmada por administración."
}
```

| Campo | Regla |
|---|---|
| `concept` | `inscripcion`, `matricula`, `mensualidad`, `mensualidad_contado`, `pago_contado`, `ciclo_completo`, `descuento` |
| `modality`, `shift` | ID declarado por el programa; `null` aplica a todas las variantes de esa dimensión |
| `amount` | Decimal exacto, preferentemente entre comillas, con hasta dos decimales |
| `currency` | Código de tres letras mayúsculas, por ejemplo `PEN` |
| `status: active` | Importe confirmado estrictamente positivo |
| `status: free` | Importe confirmado exactamente cero: `0` o `"0.00"` |
| `status: pending` | Importe no confirmado: obligatoriamente `null` |
| `status: inactive` | Fila histórica deshabilitada, que nunca se ofrece ni cobra |
| `campaign` | Identificador de campaña, sin deducir una prioridad automática |
| `starts_on`, `ends_on` | `YYYY-MM-DD` o `null`; ambos extremos son inclusivos, con fecha local Lima, UTC−05:00 |
| `promotions` | Metadatos aprobados: `id`, `description`, `kind`, `value`, `conditions` |
| `observations` | Notas administrativas; no autorizan cálculos ni cambian el estado |

Una promoción admite `kind: percent` con `value` entre 0 y 100, `fixed` con
valor no negativo, o `informative` con valor `null`. Sus condiciones son texto;
no se ejecutan como reglas ni se evalúan como código. **`amount` debe contener
el importe final aprobado para esa fila**. PricingService no aplica porcentajes,
suma mensualidades ni calcula automáticamente totales o ahorros.

Para campañas consecutivas, termina la anterior el día previo al inicio de la
siguiente. Se rechazan ventanas superpuestas del mismo concepto con variantes
coincidentes. Una fila global (`modality: null`) también entra en conflicto con
una fila de modalidad específica durante las mismas fechas: divide su alcance
o ajusta las fechas. No se elige arbitrariamente una campaña como ganadora.

Si existen varias tarifas posibles y falta modalidad o turno, Lía pide aclaración
y no abre pago. Una campaña futura o vencida no es una tarifa vigente. Sin fila
vigente, el resultado es pendiente: nunca gratuito y nunca un precio anterior.

## Recarga y seguridad comercial

La caché guarda documentos ya parseados. Cada acceso lee los archivos pequeños
y compara SHA-256 del contenido; detecta cambios incluso si conservan tamaño y
fecha de modificación. La vigencia se evalúa en cada resolución, incluso sin
editar archivos. No hay un watcher ni un proceso adicional.

Un JSON inválido, alias ambiguo, campaña superpuesta o eliminación del catálogo
bloquea la configuración comercial. No se usa una tarifa anterior de respaldo.
Corrige el archivo y vuelve a validar; la recarga se recupera automáticamente.
La validación completa del catálogo prioriza consistencia: un archivo inválido
puede bloquear los pagos de todos los programas hasta su corrección.

El LLM sólo solicita `program`, `concept`, `modality` y `shift`. Los importes,
moneda, campaña y datos de QR de una acción final son construidos por backend.
`free` se informa como gratuito y no abre QR ni upload. `pending` tampoco permite
pago. Yape se habilita para tarifas activas positivas en PEN; otras monedas se
pueden informar, pero este medio de pago no se habilita para ellas. Un descuento
no es un concepto cobrable por sí mismo.

Al enviar un comprobante se vuelve a consultar la tarifa actual. Si cambió
respecto al importe que mostraba un modal antiguo, el backend rechaza el envío.
Este flujo no reserva una tarifa ni confirma una matrícula. La asociación y
persistencia de prospectos/comprobantes sigue pendiente para su fase prevista.

## Límites de esta fase

No se ha creado un panel administrativo ni cambiado ChromaDB. El editor de JSON
y el validador son el mecanismo de administración actual. Las fechas, horarios,
beneficios y demás contradicciones académicas siguen correspondiendo a Fase 4.
