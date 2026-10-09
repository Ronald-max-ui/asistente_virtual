# Fase 4: fuentes antes de la limpieza

Captura del 7 de octubre de 2026. Documento histórico de revisión, fuera de `backend/knowledge`; no debe indexarse como conocimiento vigente. Las fechas, horarios y referencias comerciales siguientes no son una oferta actual.

## 01_institucional/admision_y_pagos.md

SHA-256 original: `57e2b6f728e686a11b23f3f6fe0b5b1327ee6b144285f7d92f9dd9d51fdacf56`

````markdown
---
id: "admision_y_pagos"
tipo: "institucional"
categoria: "01_institucional"
titulo: "Admisión, Requisitos y Métodos de Pago"
tags: ["admision", "matricula", "inscripcion", "requisitos", "documentos", "pagos", "yape", "bbva", "bcp", "cuotas", "congelamiento"]
---

# Admisión, Requisitos y Métodos de Pago

## Proceso de Admisión e Inscripción

El costo o gratuidad de la inscripción depende de la campaña vigente del programa. Consulta su archivo `*.pricing.json` mediante PricingService; un precio pendiente no significa gratuito.

El postulante puede iniciar su matrícula presentando únicamente su **Documento Nacional de Identidad (DNI)** para asegurar su vacante. Dispone de un plazo máximo de **15 días** para presentar los documentos restantes:

- Copia legible del DNI
- Certificado de estudios actualizado
- 1 fotografía tamaño carnet
- Partida de nacimiento

La vacante queda reservada formalmente con el **pago de la matrícula** del programa elegido.

## Métodos de Pago Oficiales

Los pagos pueden realizarse por los siguientes canales:

| Canal | Datos |
|---|---|
| **Yape** | A nombre de Corporativo Tuinen Star — Número: **994 773 335** |
| **Transferencia BBVA** | CCI: **011-201-000100038687-18** |
| **Transferencia BCP** | CCI: **002-28500720927504553** |

### Validación de Pago

Es obligatorio que el postulante envíe la **captura o foto del voucher de pago** por el mismo chat. Un asesor de admisiones validará el comprobante para confirmar formalmente la matrícula.

Los datos bancarios se facilitan únicamente cuando el usuario decide matricularse o solicita expresamente los datos de pago, no durante consultas de información general.

## Política de Congelamiento de Cuotas

Los montos de mensualidad se mantienen **congelados** para el estudiante mientras curse sus estudios de manera **continua y regular**.

Si el estudiante interrumpe la carrera o curso por **más de 1 año** y decide retomar, deberá sujetarse a las tarifas y costos vigentes al momento de su reincorporación.

## Pago de Matrícula por Programa

Las matrículas se consultan directamente en el archivo comercial `*.pricing.json` de cada programa, bajo `02_carreras` o `03_cursos_cortos`. No se mantienen importes duplicados en este documento.

## Beneficio por Pago Adelantado (Ciclo Completo al Contado)

Los pagos al contado, totales de ciclo y promociones dependen de la campaña vigente de cada programa y modalidad. PricingService consulta los importes finales autorizados y las condiciones de su archivo comercial; no se deducen descuentos ni totales desde este texto.
````

## 01_institucional/general.md

SHA-256 original: `4b8d60cbbba823220274b4bd4ee422ccba5b5b4bf28694e6a6c66f64d3adbcd9`

````markdown
---
id: "institucional_general"
tipo: "institucional"
categoria: "01_institucional"
titulo: "Instituto Tuinen Star — Información General"
tags: ["institucional", "sedes", "contacto", "programas", "plataformas", "beneficios", "horarios", "licenciamiento"]
---

# Instituto Superior Tuinen Star — Información General

## Identidad y Licenciamiento

El Instituto de Educación Superior Privado Tuinen Star cuenta con licenciamiento institucional otorgado por el Ministerio de Educación (MINEDU), cumpliendo con las Condiciones Básicas de Calidad. Los egresados obtienen el **Título Profesional Técnico a Nombre de la Nación** al culminar y cumplir los requisitos académicos y administrativos.

La institución opera exclusivamente en Cusco, Perú. No tiene sede ni dicta clases en Lima ni en ninguna otra ciudad.

## Programas Académicos Disponibles

### Carreras Profesionales Técnicas (2 años y medio — Título a Nombre de la Nación)

- Gastronomía
- Contabilidad
- Administración de Empresas
- Guía Oficial de Turismo

### Cursos Profesionales Cortos (3 meses — Certificación institucional)

- Curso Profesional de Panadería y Pastelería
- Curso Profesional de Bartender

La institución no ofrece carreras, especialidades ni talleres fuera de esta lista oficial.

## Sedes y Puntos de Atención

### Sede Principal — Clases y Actividades Académicas

- **Dirección:** Calle Bellavista N.º 130 y 140, distrito de San Sebastián, Cusco.
- **Referencia:** A una cuadra del carril de subida hacia el Centro Comercial Tottus.
- **Programas aquí:** Gastronomía, Contabilidad, Administración de Empresas, Guía Oficial de Turismo (clases presenciales de todos los programas).

### Oficina de Informes, Inscripción y Matrícula — Sin dictado de clases

- **Dirección:** Avenida Garcilaso N.º 304, distrito de Wanchaq, Cusco.
- **Referencia:** Frente al Mercado de Wanchaq.
- **Función:** Únicamente orientaciones, matrículas, consultas e inscripciones.

### Contacto y Horario de Atención

- **Teléfono oficial:** 949 355 435
- **Horario de atención presencial (ambas sedes):**
  - Lunes a viernes, turno mañana: 8:00 a.m. a 1:00 p.m.
  - Lunes a viernes, turno tarde: 2:00 p.m. a 7:00 p.m.

## Fechas de Inicio de Clases

- **Carreras Profesionales Técnicas** (Contabilidad, Administración, Gastronomía, Turismo): **5 de octubre de 2026**.
- **Cursos Profesionales Cortos** (Bartender, Panadería y Pastelería): **15 de noviembre**.

Las vacantes son limitadas. Se reservan formalmente con el pago de la matrícula del programa elegido.

## Modalidad Virtual y Plataformas

Aplica exclusivamente a las carreras profesionales técnicas que ofrecen turno noche virtual. **La carrera de Gastronomía NO está disponible en modalidad virtual.**

- **Clases en vivo:** Google Meet en tiempo real. Las sesiones quedan grabadas para repaso o en caso de inasistencia.
- **Gestión académica:** Plataforma Q10 para descarga de materiales, entrega de tareas, evaluaciones, calificaciones y comunicados institucionales.

## Beneficios Comunes para Estudiantes

Los siguientes beneficios aplican a todas las carreras profesionales técnicas:

- **Carnet oficial de medio pasaje** estudiantil.
- **Prácticas preprofesionales y bolsa de trabajo** a través de TUINEN JOB.
- **Continuidad universitaria (convalidación):** Permite convalidar estudios para cursar aproximadamente 2 años adicionales en la universidad y optar por un Título Profesional Universitario. La convalidación está sujeta a los convenios institucionales vigentes y a los requisitos de la universidad en convenio; no es automática ni garantizada.
- **Formación en idioma inglés** incluida en todas las carreras técnicas (excepto especificación por carrera).
- **Formación en ofimática** (Word, Excel, PowerPoint) incluida en carreras que aplica.
````

## 02_carreras/administracion.md

SHA-256 original: `f4e0e0df13c5e0a3ee4ef8ef21e9a3292297104093c0379cbf8d023c7310c6a0`

````markdown
---
id: "administracion"
tipo: "carrera_tecnica"
categoria: "02_carreras"
titulo: "Administración de Empresas"
tags: ["administracion", "empresas", "gestion", "rrhh", "marketing", "logistica", "ssoma", "costos", "horarios", "presencial", "virtual"]
inicio_clases: "2026-10-05"
duracion: "2 años y medio"
ciclos: 6
modalidad: ["presencial", "virtual"]
---

# Carrera Profesional Técnica: Administración de Empresas

## Ficha Técnica

- **Título otorgado:** Título Profesional Técnico en Administración de Empresas a Nombre de la Nación
- **Duración:** 2 años y medio (6 ciclos académicos de 17 semanas / 4 meses y medio cada uno)
- **Inicio de clases:** 5 de octubre de 2026
- **Perfil:** Forma profesionales capaces de planificar, organizar, dirigir y controlar los recursos de una organización para el crecimiento de empresas públicas, privadas o negocios propios.

## Modalidades y Horarios

### Modalidad Presencial

| Turno | Días | Horario |
|---|---|---|
| Mañana | Lunes a viernes | 7:00 a.m. a 11:30 a.m. |

**Lugar:** Sede Principal de San Sebastián (Calle Bellavista N.º 130 y 140, Cusco).

### Modalidad Virtual

| Turno | Días | Horario |
|---|---|---|
| Noche | Lunes a viernes | 6:30 p.m. a 9:30 p.m. |

Clases en vivo por Google Meet (grabadas para repaso). Gestión académica por plataforma Q10.

## Información comercial vigente

La única fuente de tarifas, campañas y promociones de este programa es [administracion.pricing.json](administracion.pricing.json).
Lía consulta PricingService directamente; los importes no dependen del índice vectorial.
No copies precios a este Markdown. Un estado `pending` no significa gratuito.


## Metodología y Herramientas

- Docentes especializados en gestión empresarial
- Aulas especializadas para simulaciones de negocios
- Análisis de casos reales del entorno empresarial peruano
- Desarrollo de proyectos empresariales propios

## Campo Laboral

El egresado puede desempeñarse en empresas privadas, instituciones públicas, entidades financieras y comerciales en áreas como:

- Administración general y operaciones
- Recursos Humanos (gestión de talento y personal)
- Finanzas, tesorería y costos
- Marketing y ventas
- Logística y compras
- Procesos productivos y control de calidad
- Seguridad, Salud Ocupacional y Medio Ambiente (SSOMA)
- Creación, dirección y gestión de emprendimientos propios
````

## 02_carreras/contabilidad.md

SHA-256 original: `6a8988e49cf683492364abb82bf4b75005b234d2c8b78fe14c85e89e2ea81fbd`

````markdown
---
id: "contabilidad"
tipo: "carrera_tecnica"
categoria: "02_carreras"
titulo: "Contabilidad"
tags: ["contabilidad", "contable", "finanzas", "tributaria", "auditoria", "costos", "horarios", "presencial", "virtual"]
inicio_clases: "2026-10-05"
duracion: "2 años y medio"
ciclos: 6
modalidad: ["presencial", "virtual"]
---

# Carrera Profesional Técnica: Contabilidad

## Ficha Técnica

- **Título otorgado:** Título Profesional Técnico en Contabilidad a Nombre de la Nación
- **Duración:** 2 años y medio (6 ciclos académicos de 17 semanas / 4 meses y medio cada uno)
- **Inicio de clases:** 5 de octubre de 2026
- **Perfil:** Gestión de información financiera, contable, tributaria y auditoría para la toma de decisiones y control financiero en entidades públicas, privadas o de manera independiente.

## Modalidades y Horarios

### Modalidad Presencial

| Turno | Días | Horario |
|---|---|---|
| Mañana | Lunes a viernes | 7:00 a.m. a 11:30 a.m. |
| Tarde | Lunes a viernes | (consultar disponibilidad por ciclo) |

**Lugar:** Sede Principal de San Sebastián (Calle Bellavista N.º 130 y 140, Cusco).

### Modalidad Virtual

| Turno | Días | Horario |
|---|---|---|
| Noche | Lunes a viernes | 6:30 p.m. a 9:30 p.m. |

Clases en vivo por Google Meet (grabadas para repaso). Gestión académica por plataforma Q10.

## Información comercial vigente

La única fuente de tarifas, campañas y promociones de este programa es [contabilidad.pricing.json](contabilidad.pricing.json).
Lía consulta PricingService directamente; los importes no dependen del índice vectorial.
No copies precios a este Markdown. Un estado `pending` no significa gratuito.


## Herramientas y Formación Especializada

- **Software contable especializado** (aplicado al contexto empresarial peruano)
- **Certificaciones progresivas** durante el avance de la carrera
- Metodología: casos prácticos reales y simulaciones de operaciones financieras

## Campo Laboral

El egresado puede desempeñarse en:

- Bancos, cajas municipales, cajas rurales y cooperativas de ahorro y crédito
- Empresas financieras y compañías de seguros
- Estudios contables y empresas consultoras
- Áreas contables, financieras, de tesorería y tributarias
- Control de ingresos, cobranzas, presupuestos y costos
- Auditoría y control interno
- Empresas de sectores industriales, comerciales o de servicios
- Asesoría contable independiente o negocio propio
````

## 02_carreras/gastronomia.md

SHA-256 original: `0b20d5d66cbb92c0665e565f44043ec5608dcaf70b04fba6bb8beeb96404a376`

````markdown
---
id: "gastronomia"
tipo: "carrera_tecnica"
categoria: "02_carreras"
titulo: "Gastronomía"
tags: ["gastronomia", "culinaria", "cocina", "presencial", "costos", "horarios", "turno_manana", "turno_sabado", "uniforme", "insumos"]
inicio_clases: "2026-10-05"
duracion: "2 años y medio"
ciclos: 6
modalidad: ["presencial"]
---

# Carrera Profesional Técnica: Gastronomía

## Ficha Técnica

- **Título otorgado:** Título Profesional Técnico en Gastronomía a Nombre de la Nación
- **Duración:** 2 años y medio (6 ciclos académicos de 17 semanas / 4 meses y medio cada uno)
- **Inicio de clases:** 5 de octubre de 2026
- **Perfil:** Formación práctica para desarrollar técnicas culinarias, gestión gastronómica y operación en cocina en ambientes especializados.

## Modalidad y Horarios

> **IMPORTANTE:** La carrera de Gastronomía es **100% presencial** en todos sus turnos. No se ofrece en modalidad virtual ni a distancia.

### Turno Lunes a Viernes (Presencial)

| Turno | Días | Horario |
|---|---|---|
| Mañana | Lunes a viernes | 7:00 a.m. a 11:30 a.m. |
| Noche | Lunes a viernes | 6:30 p.m. a 9:30 p.m. |

### Turno Sábados (Presencial — Para personas que trabajan entre semana)

| Turno | Días | Horario |
|---|---|---|
| Sábado | Sábados | 8:00 a.m. a 6:30 p.m. |

**Lugar de clases:** Sede Principal de San Sebastián (Calle Bellavista N.º 130 y 140, Cusco).

## Información comercial vigente

La única fuente de tarifas, campañas y promociones de este programa es [gastronomia.pricing.json](gastronomia.pricing.json).
Lía consulta PricingService directamente; los importes no dependen del índice vectorial.
No copies precios a este Markdown. Un estado `pending` no significa gratuito.


## Beneficios e Implementos Incluidos

Con el pago de la matrícula, el estudiante recibe:

- **Uniforme completo institucional**
- **Insumos** para la totalidad de las prácticas culinarias
- **Uso de utensilios, equipos y menajería** del instituto en los talleres
- **Material académico complementario**

**Únicos implementos personales requeridos:** tabla de picar y un cuchillo propios.

### Metodología de Taller

- Prácticas culinarias desde el **primer ciclo**
- Máximo **25 estudiantes por taller** para garantizar enseñanza personalizada

## Campo Laboral

El egresado puede desempeñarse en:

- Restaurantes y cadenas gastronómicas
- Hoteles y centros de alojamiento
- Cafeterías, pastelerías y reposterías
- Bares y coctelería
- Empresas de catering y eventos
- Creación y gestión de negocios gastronómicos propios
````

## 02_carreras/turismo.md

SHA-256 original: `5190318d812ed83cfd6cf1dcc60d8d668210b0f529777802d5928aa1a2db2d70`

````markdown
---
id: "turismo"
tipo: "carrera_tecnica"
categoria: "02_carreras"
titulo: "Guía Oficial de Turismo"
tags: ["turismo", "guia", "viajes", "cultura", "patrimonio", "japones", "ingles", "costos", "horarios", "presencial", "virtual", "salidas_campo"]
inicio_clases: "2026-10-05"
duracion: "2 años y medio"
ciclos: 6
modalidad: ["presencial", "virtual"]
---

# Carrera Profesional Técnica: Guía Oficial de Turismo

## Ficha Técnica

- **Título otorgado:** Título Profesional Técnico en Guía Oficial de Turismo a Nombre de la Nación
- **Duración:** 2 años y medio (6 ciclos académicos de 17 semanas / 4 meses y medio cada uno)
- **Inicio de clases:** 5 de octubre de 2026
- **Perfil:** Formación práctica y teórica para guiar e interpretar atractivos turísticos, gestionar servicios turísticos y trabajar con cultura, historia y patrimonio del destino Cusco y el Perú.

## Modalidades y Horarios

### Modalidad Presencial

| Turno | Días | Horario |
|---|---|---|
| Mañana | Lunes a viernes | 7:00 a.m. a 11:30 a.m. |
| Tarde | Lunes a viernes | (consultar disponibilidad por ciclo) |

**Lugar:** Sede Principal de San Sebastián (Calle Bellavista N.º 130 y 140, Cusco).

### Modalidad Virtual

| Turno | Días | Horario |
|---|---|---|
| Noche | Lunes a viernes | 6:30 p.m. a 9:30 p.m. |

Clases en vivo por Google Meet (grabadas para repaso). Gestión académica por plataforma Q10.

## Información comercial vigente

La única fuente de tarifas, campañas y promociones de este programa es [turismo.pricing.json](turismo.pricing.json).
Lía consulta PricingService directamente; los importes no dependen del índice vectorial.
No copies precios a este Markdown. Un estado `pending` no significa gratuito.


## Diferenciador Exclusivo: Formación en Idiomas

Esta carrera incluye formación integrada en **dos idiomas**:

- **Inglés** — con certificaciones progresivas según nivel alcanzado
- **Japonés** — con certificaciones progresivas según nivel alcanzado

Es la única carrera del instituto con formación en japonés.

## Formación Práctica desde el Primer Ciclo

- **Salidas de campo** y visitas académicas desde el primer ciclo
- Recorridos turísticos guiados y visitas a museos
- Caminatas interpretativas y actividades de turismo alternativo y aventura
- Atractivos naturales y recursos culturales del Cusco

### Áreas de Especialización

- Turismo cultural e histórico
- Turismo de naturaleza y medio ambiente
- Turismo alternativo y de aventura
- Técnicas de comunicación, guiado e interpretación
- Gestión de servicios turísticos

## Campo Laboral

El egresado puede desempeñarse en:

- Agencias de viajes y turismo
- Empresas operadoras de turismo receptivo y emisivo
- Hoteles y cadenas de hospedaje
- Museos y centros de interpretación cultural o natural
- Empresas de servicios y transporte turístico
- Creación y desarrollo de emprendimientos turísticos propios
````

## 03_cursos_cortos/bartender.md

SHA-256 original: `ebc731b956727bbb41618c4e450cea6607e4d1116dfae89582f42213d17ede42`

````markdown
---
id: "bartender"
tipo: "curso_corto"
categoria: "03_cursos_cortos"
titulo: "Curso Profesional de Bartender"
tags: ["bartender", "cocteleria", "mixologia", "flair", "mocktails", "curso_corto", "sabados", "certificado", "emprendimiento"]
inicio_clases: "2026-11-15"
duracion: "3 meses"
modalidad: ["presencial"]
---

# Curso Profesional: Bartender — Mixología y Coctelería

## Ficha Técnica

- **Certificación otorgada:** Certificado en Bartender Profesional — Mixología, Flair y Coctelería Moderna, emitido por el Instituto Tuinen Star (institución licenciada por el MINEDU).
- **Nivel:** Curso de especialización práctica. Al culminar se obtiene **certificación institucional**, NO un Título Profesional Técnico.
- **Duración:** 3 meses
- **Inicio oficial:** 15 de noviembre
- **Requisitos previos:** Ninguno. No se necesita experiencia previa; está diseñado para aprender desde cero o perfeccionar técnicas.

## Modalidad, Horarios y Sede

- **Modalidad:** 100% presencial y práctica desde la primera sesión
- **Frecuencia:** Exclusivamente los días **sábados**
- **No disponible** en modalidad virtual ni a distancia

| Turno | Horario |
|---|---|
| Mañana | Sábados de 9:00 a.m. a 12:00 p.m. |
| Tarde | Sábados de 3:00 p.m. a 6:00 p.m. |

**Lugar de clases:** Sede Principal de San Sebastián (Calle Bellavista N.º 130 y 140, Cusco).

## Información comercial vigente

La única fuente de tarifas, campañas y promociones de este programa es [bartender.pricing.json](bartender.pricing.json).
Lía consulta PricingService directamente; los importes no dependen del índice vectorial.
No copies precios a este Markdown. Un estado `pending` no significa gratuito.

**Cupos estrictamente limitados** por turno. Se asignan por orden de matrícula.

**Requisitos para inscribirse:**
- Copia del DNI
- Ficha de inscripción completada
- Pago de matrícula para reservar vacante


## Contenido Temático

El curso desarrolla competencias prácticas y de gestión:

- Mixología moderna y coctelería de autor
- Coctelería clásica e internacional
- Flair bartending (técnicas de exhibición y servicio)
- Mocktails (coctelería y bebidas sin alcohol)
- Técnicas profesionales de preparación y presentación de cocteles
- Administración de bares, costeo de bebidas y control de inventarios
- Estrategias de emprendimiento y apertura de negocios de coctelería

## Beneficios Incluidos

- Insumos para todas las sesiones prácticas
- **Delantal profesional de barman**
- **Recetario oficial de coctelería**
- **Sesión fotográfica profesional** para portafolio personal
- Docentes con experiencia en el rubro gastronómico y hotelero

## Campo Laboral

El egresado puede desempeñarse en bares, cadenas hoteleras, restaurantes, empresas de eventos sociales y corporativos, discotecas, cruceros o emprendimientos propios de coctelería.
````

## 03_cursos_cortos/panaderia_pasteleria.md

SHA-256 original: `bb77b11d3d23b85c44591e74f36aca6683b89c2591ac677e6ebd7f1470f7b181`

````markdown
---
id: "panaderia_pasteleria"
tipo: "curso_corto"
categoria: "03_cursos_cortos"
titulo: "Curso Profesional de Panadería y Pastelería"
tags: ["panaderia", "pasteleria", "reposteria", "fondant", "buttercream", "curso_corto", "sabados", "certificado", "emprendimiento", "gastronomia"]
inicio_clases: "2026-11-15"
duracion: "3 meses"
modalidad: ["presencial"]
---

# Curso Profesional: Panadería y Pastelería

## Ficha Técnica

- **Certificación otorgada:** Certificación a nombre del Instituto Tuinen Star al culminar y aprobar satisfactoriamente el curso.
- **Nivel:** Curso profesional corto. Al culminar se obtiene **certificación institucional**, NO un Título Profesional Técnico.
- **Duración:** 3 meses
- **Inicio oficial:** 15 de noviembre
- **Público objetivo:** Emprendedores que buscan iniciar su propio negocio gastronómico y personas interesadas en aprender o perfeccionar técnicas de panadería y pastelería.

## Modalidad, Horarios y Sede

- **Modalidad:** 100% presencial y práctica. No disponible en modalidad virtual ni a distancia.
- **Frecuencia:** Exclusivamente los días **sábados**

| Turno | Horario |
|---|---|
| Mañana | Sábados de 8:00 a.m. a 12:00 p.m. |
| Tarde | Sábados de 2:00 p.m. a 6:00 p.m. |

**Lugar de clases:** Sede Principal de San Sebastián (Calle Bellavista N.º 130 y 140, Cusco).

## Información comercial vigente

La única fuente de tarifas, campañas y promociones de este programa es [panaderia_pasteleria.pricing.json](panaderia_pasteleria.pricing.json).
Lía consulta PricingService directamente; los importes no dependen del índice vectorial.
No copies precios a este Markdown. Un estado `pending` no significa gratuito.

**Cupos limitados por turno.** Se asignan por orden de matrícula.


## Contenido Temático

Durante las sesiones prácticas los alumnos aprenden:

### Panadería
- Elaboración de panes internacionales
- Elaboración de panes regionales (panes típicos del Cusco y Perú)

### Pastelería
- Pastelería básica
- Pastelería avanzada

### Técnicas de Decoración
- Decoración con masa fondant
- Decoración con buttercream
- Decoración con chantilly
- Elaboración y aplicaciones de crema pastelera

## Campo Laboral

El egresado puede emprender su propio negocio de panadería o pastelería, trabajar en panaderías, pastelerías, cafeterías, hoteles, restaurantes o empresas de catering.
````

## 04_faqs/preguntas_frecuentes.md

SHA-256 original: `90bc472b689f5ae80a7ab9f87dc6a0a1b41cfc1af12027d000ed03501531b311`

````markdown
---
id: "faqs"
tipo: "faq"
categoria: "04_faqs"
titulo: "Preguntas Frecuentes — Instituto Tuinen Star"
tags: ["faq", "preguntas", "respuestas", "admision", "pagos", "horarios", "modalidad", "requisitos", "virtual", "presencial", "gastronomia", "turismo", "contabilidad", "administracion"]
---

# Preguntas Frecuentes — Instituto Tuinen Star

## Sobre la Institución

**¿El instituto tiene sede en Lima?**
No. El Instituto Tuinen Star opera únicamente en Cusco, Perú. Las clases se dictan en la Sede Principal de San Sebastián y la oficina de inscripciones está en Wanchaq.

**¿Cuántas sedes tienen?**
Dos puntos: la Sede Principal en San Sebastián (Calle Bellavista 130 y 140) donde se dictan todas las clases, y la Oficina de Wanchaq (Av. Garcilaso 304, frente al Mercado de Wanchaq) solo para informes, inscripciones y matrículas.

**¿Cuál es el teléfono de contacto?**
949 355 435. Atención de lunes a viernes en dos turnos: mañana de 8:00 a.m. a 1:00 p.m. y tarde de 2:00 p.m. a 7:00 p.m.

---

## Sobre Admisión y Matrícula

**¿Qué necesito para matricularme?**
Solo tu DNI para iniciar la matrícula y reservar tu vacante. Tienes hasta 15 días para regularizar el certificado de estudios, la fotografía tamaño carnet y la partida de nacimiento.

**¿La inscripción tiene costo?**
El importe o gratuidad se consulta en PricingService desde el archivo comercial del programa y su campaña vigente. Un estado pendiente no significa gratuito.

**¿Cómo reservo mi vacante?**
La vacante se reserva formalmente con el pago de la matrícula del programa elegido. Las vacantes son limitadas.

**¿Cuándo empiezan las clases?**
Las carreras profesionales técnicas (Gastronomía, Contabilidad, Administración, Turismo) inician el **5 de octubre de 2026**. Los cursos cortos de Bartender y Panadería y Pastelería inician el **15 de noviembre**.

---

## Sobre Pagos

**¿Cómo puedo pagar la matrícula o las cuotas?**
Por Yape al número 994 773 335 (a nombre de Corporativo Tuinen Star), por transferencia BBVA al CCI 011-201-000100038687-18, o por transferencia BCP al CCI 002-28500720927504553. Luego debes enviar la foto del voucher por el chat para que un asesor confirme tu matrícula.

**¿Las cuotas pueden subir si sigo estudiando regularmente?**
No. Los montos se mantienen congelados mientras estudies de manera continua y regular. Solo cambian si interrumpes la carrera por más de 1 año y decides retomar.

**¿Hay descuento si pago el ciclo completo al contado?**
Las promociones y los importes finales dependen de la campaña, programa y modalidad. Consulta PricingService; no se aplica un porcentaje general ni se deducen ahorros desde el contenido informativo.

---

## Sobre Modalidades y Horarios

**¿Puedo estudiar de noche de forma virtual?**
Sí, en Contabilidad, Administración de Empresas y Guía Oficial de Turismo hay turno noche virtual de lunes a viernes de 6:30 p.m. a 9:30 p.m. por Google Meet. Las clases quedan grabadas.

**¿Gastronomía tiene modalidad virtual?**
No. Gastronomía es 100% presencial en todos sus turnos. No tiene modalidad virtual ni a distancia.

**¿Gastronomía tiene clases los sábados?**
Sí. Hay una modalidad de fin de semana presencial los sábados de 8:00 a.m. a 6:30 p.m., diseñada para personas que trabajan entre semana.

**¿Los cursos de Bartender y Panadería tienen clases entre semana?**
No. Ambos cursos se dictan exclusivamente los sábados. Bartender tiene turnos de 9:00 a.m. a 12:00 p.m. y de 3:00 p.m. a 6:00 p.m. Panadería tiene turnos de 8:00 a.m. a 12:00 p.m. y de 2:00 p.m. a 6:00 p.m.

**¿Si no puedo asistir a una clase virtual, la puedo ver después?**
Sí. Todas las clases virtuales quedan grabadas y disponibles en la plataforma Q10 para repaso o en caso de inasistencia.

---

## Sobre los Programas

**¿Qué título obtengo al terminar una carrera técnica?**
Título Profesional Técnico a Nombre de la Nación, emitido por el Instituto Tuinen Star con respaldo del MINEDU.

**¿El certificado de Bartender o Panadería equivale a un título técnico?**
No. Los cursos cortos entregan una certificación institucional del Instituto Tuinen Star, no un Título Profesional Técnico.

**¿Cuál carrera enseña japonés?**
Guía Oficial de Turismo. Es la única carrera que incluye formación en inglés y japonés con certificaciones progresivas de idiomas.

**¿Puedo continuar estudiando en la universidad después de terminar una carrera técnica?**
Sí. El instituto tiene convenios de continuidad universitaria que permiten convalidar estudios y cursar aproximadamente 2 años adicionales para obtener un Título Profesional Universitario. La convalidación no es automática; depende de los convenios vigentes y los requisitos de la universidad en convenio.

**¿Tienen bolsa de trabajo?**
Sí. Todos los egresados de carreras técnicas tienen acceso a prácticas preprofesionales y oportunidades laborales a través de TUINEN JOB.

**¿Necesito experiencia previa para el curso de Bartender?**
No. El curso está diseñado para aprender desde cero. No se requiere experiencia previa.

---

## Sobre Gastronomía en Detalle

**¿Cuánto cuesta la matrícula de Gastronomía?**
Consulta la matrícula vigente de Gastronomía en su archivo `02_carreras/gastronomia.pricing.json` mediante PricingService, indicando modalidad y turno si hay tarifas diferentes.

**¿Qué implementos debo llevar a Gastronomía?**
Solo tu tabla de picar y un cuchillo. Todo lo demás —uniforme, insumos, utensilios y equipos— está incluido.

**¿Cuántos alumnos hay por clase en Gastronomía?**
Máximo 25 estudiantes por taller para garantizar una enseñanza personalizada.
````
