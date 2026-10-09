# Fase 9B — Lía Admin

## Resultado y alcance

Panel HTML/CSS/JavaScript modular en `/admin/`, separado del frontend público. No se incorporaron frameworks ni dependencias. No se modificaron precios operativos, usuarios reales, bases oficiales, Markdown, índice vectorial, avatar, estilos públicos ni contratos de chat/SSE. Las pruebas comerciales se ejecutaron exclusivamente con bases y comprobantes temporales.

La interfaz llama a la API administrativa existente. CommercialService, PricingService, RBAC, ConsentService, ActionService y repositorios conservan las reglas de negocio. Se ampliaron únicamente los adaptadores necesarios para presentación, transacciones de campañas, paginación y control optimista.

## 1. Estructura visual

Cabecera Lía Admin, identidad y cierre de sesión; navegación lateral; contenido con tarjetas, filtros, tablas y formularios. Menú colapsable en móvil, tablas con scroll propio, desktop/tablet como prioridad. CSS y JavaScript administrativos no se cargan en Lía pública. Se instaló un favicon propio reutilizando el SVG institucional existente.

Módulos: Dashboard, Programas, Precios, Campañas, Avatares, Apariencia, Prospectos, Comprobantes, Usuarios, Auditoría y Configuración. El último explica la configuración de instancia y las capacidades existentes; no expone un editor arbitrario de JSON, secretos o parámetros de despliegue.

Capturas sintéticas: `fase-9b-dashboard.png` y `fase-9b-mobile.png`. La fixture comienza con un avatar ausente para comprobar que el dashboard muestra atención requerida; posteriormente selecciona el avatar instalado.

## 2. Permisos por pantalla

| Rol | Pantallas / operaciones |
| --- | --- |
| superadmin | Todas; escritura comercial, usuarios, revocación y revisión de comprobantes |
| administrador | Programas, precios, campañas, avatares y apariencia con edición; prospectos y comprobantes en lectura; auditoría |
| admisiones | Prospectos, programas, precios y campañas en lectura |
| revisor_pagos | Comprobantes y revisión pendiente |
| solo_lectura | Recursos permitidos de programas, precios, campañas, avatares, apariencia, prospectos y comprobantes sin edición |

Dashboard omite tarjetas cuyos datos no están autorizados. Usuarios requiere users.read, edición users.write; auditoría e historial requieren audit.read. El backend continúa validando cada permiso y la vigencia del usuario; ninguna autorización depende de ocultar un botón.

## 3. Sesión, formularios y accesibilidad

Al abrir se consulta `/auth/me`. Cookies HttpOnly existentes, CSRF en memoria para mutaciones y ninguna credencial en storage del navegador. Login separado; contraseña se limpia de la entrada al enviar. Peticiones privadas no-store, sin reintentos automáticos de operaciones.

La expiración muestra login y conserva el formulario en memoria de esa pestaña. Sólo la misma identidad puede recuperarlo; un acceso con otra identidad descarta el borrador por privacidad. No se conservan contraseñas en borradores. Cerrar sesión descarta datos y formularios; recargar/cerrar la pestaña elimina los borradores. Un registro cambiado mientras la sesión expiraba sigue sujeto a comprobación de versión.

Diálogos nativos con role/dialog, aria-modal, título accesible, foco inicial, trap explícito de Tab/Shift+Tab, Escape cuando no hay envío activo y devolución del foco a un elemento conectado. Formularios con labels únicos, ayudas, validación junto al campo, botones deshabilitados al enviar, error controlado y confirmación financiera. Toasts accesibles y acotados a dos para evitar cubrir toda la pantalla y acumular timers. Carga marcada con aria-busy y protección contra respuestas de navegación obsoletas.

## 4. Programas

Crear y editar nombre, tipo, alias, disponibilidad, modalidades, turnos y referencia académica. El ID de un programa existente es inmutable en el formulario y la API mantiene la comprobación de ID de ruta/cuerpo.

Modalidades y turnos se presentan como disponibilidades independientes, porque el modelo vigente no define una matriz de combinaciones. El panel no inventa modalidades ni turnos compartidos. Cambios incompatibles con tarifas existentes siguen rechazados por CommercialService e integridad referencial.

## 5. Precios

Filtros por programa, modalidad, turno, concepto y estado. Se distingue Activo, Gratis, Pendiente e Inactivo. Pendiente/null se muestra como «Pendiente», nunca S/ 0; gratuito confirmado muestra S/ 0.00. Los importes se validan y envían como strings decimales; no se usa float JS para calcular dinero.

El formulario conserva promociones y periodos existentes, admite observación y confirma Antes/Nuevo antes de guardar. IDs de nuevas tarifas los genera la UI como identificadores opacos; las reglas monetarias y conflictos se validan en backend. Inactivo puede conservar importe o null y no se usa para cobro.

Las filas indican ofertas y vigencia; para el precio base, la campaña efectiva y su importe se consultan a PricingService en backend. La UI no calcula precedencia ni determina el precio vigente. El historial consulta auditoría filtrada/paginada por ID de tarifa y presenta fecha, persona, antes y después.

## 6. Campañas

Formulario de nombre, programa, modalidad, turno, concepto, estado/importe promocional, moneda, inicio/fin, habilitación y notas. Muestra el precio base obtenido del nuevo método PricingService.resolve_base, que usa el mismo resolvedor excluyendo ofertas; no calcula un importe en frontend.

Vigencia calculada por backend con el reloj comercial de PricingService, America/Lima, fechas inclusivas: próxima, activa, finalizada o deshabilitada. La UI no usa su reloj para decidir validez comercial.

Campaña y oferta se guardan en una única transacción con validación de toda la configuración y dos entradas de auditoría. Un conflicto revierte ambas y muestra «Ya existe una tarifa o campaña para esta combinación y periodo». Editar una oferta conserva las otras; cambiar fechas afecta todas las ofertas de la campaña, con advertencia explícita. Un encabezado de campaña antiguo sin oferta puede recibir su primera oferta sin recrearlo. Los descuentos/promociones previos se preservan; no se introduce un constructor de promociones arbitrario.

## 7. Avatares y apariencia

Selección de avatares ya instalados, nombre, ruta aprobada, estado y fallback gráfico ligero. No se carga Three.js/VRM dentro del panel ni se implementa upload. Activar llama al servicio existente, actualiza selección única y genera auditoría. `/api/config` devuelve el avatar seleccionado en la siguiente carga.

Apariencia edita exclusivamente campos existentes: assistant_name, logo_url, favicon_url, primary_color, initial_message y kiosk_text_enabled. Voz, extensiones y selección actual se conservan en la petición completa. Logo/favicon deben usar recursos instalados en rutas aprobadas. No se promete personalización pública de campos que el frontend actual aún no consume.

## 8. Prospectos y comprobantes

Prospectos sólo lectura, 20 filas por página, consulta de 21 para determinar siguiente página. Fecha, nombre, WhatsApp, programa, modalidad, origen y etapa de sesión. Nada de PII en navegación, URLs, logs del navegador o storage. Consulta de PII sólo con permisos existentes.

Comprobantes paginados y filtrados por estado desde SQL del repositorio. Muestran prospecto asociado, concepto, importe y revisión. Imagen mediante ID de voucher autenticado; no se acepta un path de archivo. El servicio valida referencia UUID/extensión instalada, pertenencia al directorio privado y existencia. Respuesta inline de imagen, MIME aprobado, nosniff y no-store; ninguna ruta local en JSON.

Sólo pending_review puede pasar a approved/rejected, con nota opcional y auditoría existentes. El panel aclara que es revisión administrativa, no conciliación bancaria ni confirmación automática por subir imagen. Las transiciones finales y carreras/tarifas del upload público permanecen protegidas.

## 9. Usuarios y auditoría

Listado paginado, creación, nombre, rol, habilitación, cambio de contraseña y revocación de todas las sesiones mediante APIs de 9A. Se conservan el hash Argon2id, política de contraseña y protección del último superadmin. Los listados/respuestas nunca incluyen hashes.

Auditoría paginada con filtros de actor ID, acción, recurso, fecha desde/hasta e ID de recurso para historial. Fechas filtradas en America/Lima. Los filtros se aplican en repositorios de ambas bases con parámetros SQL. Snapshots permitidos y presentación legible, incluyendo concepto/programa/importe antes/después; no se altera el registro original. Se conservan snapshots de precios previos sin volverlos vigentes.

## 10. Concurrencia y endpoints

ETag opaco derivado del registro/settings; el panel captura la versión al abrir el formulario y envía If-Match. CommercialService y el repositorio de usuarios comparan dentro de BEGIN IMMEDIATE. Campañas comparan las revisiones de encabezado y oferta; selección de avatar compara configuración. Un cambio concurrente devuelve 409 admin_record_changed y pide recargar. Tras guardar se vuelve a consultar backend.

Compatibilidad: las APIs originales aceptan todavía escrituras sin If-Match para scripts/pruebas anteriores. El panel lo utiliza para registros existentes. Forzar precondición para todos los clientes es una migración posterior; un escritor legado sin versión puede sobrescribir y debe ser retirado o actualizado administrativamente. No hay locks prolongados ni cambios de esquema SQLite.

Nuevas rutas protegidas:

- GET /api/admin/panel/context: catálogos permitidos, fecha comercial, estados derivados y revisiones.
- GET /api/admin/panel/dashboard: resumen por permisos y health simplificado.
- GET /api/admin/panel/base-price: precio base desde PricingService.
- POST /api/admin/panel/campaign-offer: campaña y oferta atómicas, permisos campaigns.write + prices.write.
- GET /api/admin/panel/vouchers/{id}/file: imagen privada, vouchers.read.
- GET /api/admin/users/{id}: ficha pública administrativa y ETag, users.read.

Se ampliaron filtros de /api/admin/vouchers y /api/admin/audit. Rutas públicas, auth/CSRF/RBAC, pricing, sesiones y SSE conservan contratos. Bearer legado permanece explícitamente separado; el panel no lo utiliza.

## 11. Pruebas y verificación panel → Lía

E2E Chrome/Uvicorn reales, bases temporales, LLM/TTS/RAG de fixture sin proveedores externos. La persistencia, API pública, ConversationService, PricingService, consentimiento y acciones son reales. Se editó Turismo inscripción de 80 a 120.50 desde formulario y /chat respondió 120.5 desde el catálogo; luego una campaña gratis hizo responder gratuidad sin QR. Sin build intermedio, sin tocar Markdown y sin regenerar ChromaDB. Los números son exclusivamente datos sintéticos de prueba; no confirman nuevas tarifas institucionales.

Se probaron además programa, gratis/null, conflictos, avatar y /api/config, prospecto, imagen privada, aprobación, usuarios/roles, auditoría, expiración, recuperación del borrador, focus trap/Escape, tablet/móvil y sólo lectura con 403 backend. El E2E público conservó sus 18 controles/3 rondas.

Comandos reproducibles:

```powershell
backend/venv/Scripts/python.exe -B -m unittest discover -s backend/tests
npm --prefix avatar-kiosk test
backend/venv/Scripts/python.exe -B backend/admin_e2e.py --output docs/fase-9b-admin-e2e.json
backend/venv/Scripts/python.exe -B backend/browser_e2e.py --production-build --rounds 3 --output docs/fase-9b-public-e2e.json
backend/venv/Scripts/python.exe -B backend/verify_admin_panel.py
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --check
backend/venv/Scripts/python.exe -B backend/rebuild_knowledge.py --evaluate
npm --prefix avatar-kiosk run build
backend/venv/Scripts/python.exe -B backend/scan_secrets.py
git diff --check
```

Resultado: 226 pruebas backend (213 anteriores + 13 nuevas), 54 frontend (44 anteriores + 10 nuevas), 40 controles E2E administrativos y 18 públicos. Todas aprobadas. Sintaxis: 115 archivos Python y 31 JavaScript. Escaneo de secretos: sin hallazgos. Resultado consolidado en fase-9b-validation.json y los informes E2E/producción. Verificación de producción: configuración segura aceptada y cookies inseguras, HTTP/localhost, Bearer incompleto/placeholder, Argon2 débil y sesiones excesivas rechazados. Backup SQLite consistente temporal, integridad y presencia de identidad/auditoría validadas sin restauraciones destructivas. Índice oficial ready, colección/modelo/chunking sin cambios. Build público conserva la advertencia previa del chunk Three.js 610.23 KB.

## 12. Archivos

Nuevos: domain/revision.py, services/admin_panel_service.py, api/admin_panel.py, verify_admin_panel.py, tests/test_phase9b.py; static/admin/{ui.js,navigation.js,commercialScreens.js,operationalScreens.js,userScreens.js,favicon.svg}; avatar-kiosk/tests/adminPanel.test.js e informes/capturas de esta fase.

Modificados: server.py; api/{commercial,admin_identity}.py; services/{commercial_service,pricing_service,admin_service}.py; persistence/{audit,sqlite_admin_repository,sqlite_runtime_repository,admin_repository,runtime_repository}.py; security/http.py; static/admin/{index.html,admin.css,adminClient.js,admin.js}; admin_e2e.py y tests/admin_e2e_app.py. No se añadieron tablas ni dependencias.

## 13. Pendientes y riesgos

Aceptación humana con personal administrativo, lector de pantalla y tablets/teléfonos físicos; Chrome a distintos tamaños no certifica Safari/iOS ni hardware real. Configurar y verificar HTTPS/reverse proxy/ACL/backups cifrados y usuarios nominales en el servidor final; no se desplegó en producción ni se creó un usuario real.

Actualizar/retirar scripts sin If-Match y Bearer compartido. Paginación offset conserva el límite de 10 000 de las APIs actuales; ante volumen mayor conviene cursor/índices adicionales, sin cambiar silenciosamente el contrato ahora. El selector de actor de auditoría muestra hasta 100 usuarios, mientras Usuarios está paginado. Borradores sólo duran esa pestaña; no hay recuperación persistente.

Configurar retención administrativa y de PII según decisión institucional; no se añadió eliminación automática. Sin upload VRM, vista previa 3D, editor genérico de voz/extensiones, CRM, analytics, multitenant, Redis o PostgreSQL. Los pendientes de MFA/recuperación de identidad y despliegue de 9A continúan. No se inició Fase 9C.
