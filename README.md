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

# Crea entorno virtual
python -m venv venv
venv\Scripts\activate  # o source venv/bin/activate en Linux

# Instala dependencias
pip install -r requirements.txt
