# Ryu Project - Monitoreo y Gestión de Redes SDN

Este proyecto implementa un sistema de monitoreo y gestión de tráfico en redes definidas por software (SDN) utilizando el controlador Ryu.

## 📦 Características

- Controlador SDN personalizado usando Ryu
- Visualización de estadísticas de tráfico (puertos, flujos, etc.)
- Panel de control para gestión de dispositivos conectados
- Modulo de clasificacion de trafico con Machine Learning

## 🚀 Requisitos

- Python 3.8+
- Ryu Framework
- Git
- pip
- Ubuntu 20.04 (recomendado)
- wheel
- eventlet 0.30.2

## ⚙️ Instalación

```bash
# Clona el repositorio
git clone https://github.com/jcm78411/ryu-project.git
cd ryu-project
```

# Crea el entorno virtual
```bash
python -m venv .venv
```

# Activa el entorno virtual en Windows con
```bash
.venv\Scripts\activate
```

# O si estás en Linux/MacOS con
```bash
source .venv/bin/activate
```

# Instala dependencias

```bash
pip install -r requirements.txt
```

# Recuerda instalar las herramientas necesarias antes...

# Y tambien si te da algún error de politica de ejecucion de scripts:

# En una terminal de Windows ejecuta:

```bash
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```