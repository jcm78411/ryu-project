import time
import csv
import psutil
import subprocess
import platform
import socket

def obtener_latencia(host):
    try:
        param = "-n" if platform.system().lower() == "windows" else "-c"
        resultado = subprocess.run(["ping", param, "1", host], capture_output=True, text=True)
        print("Salida capturada:")
        print(resultado.stdout)
        if resultado.returncode == 0:
            for linea in resultado.stdout.splitlines():
                if "tiempo=" in linea.lower():
                    tiempo = linea.lower().split("tiempo=")[1].split("ms")[0].strip()
                    print("Latencia encontrada:", tiempo, "ms")
                    return int(tiempo)
                elif "time=" in linea.lower():
                    tiempo = linea.lower().split("time=")[1].split("ms")[0].strip()
                    print("Latencia encontrada:", tiempo, "ms")
                    return int(tiempo)
        else:
            print("No se recibio respuesta del host, latencia = 9999 ms")
    except Exception as e:
        print("Error obteniendo latencia:", e)
    return 9999

def registrar_datos(interface_name, intervalo=1, archivo="datos_red.csv"):
    try:
        with open(archivo, mode='x', newline='') as f:
            escritor = csv.writer(f)
            escritor.writerow(["timestamp", "tx_bytes", "rx_bytes", "tx_packets", "rx_packets", "latencia"])
    except FileExistsError:
        pass

    gateway = "192.168.42.1"
    if not gateway:
        print("No se pudo detectar la puerta de enlace.")
        return

    print(f"Usando {gateway} para medir latencia.")

    while True:
        stats = psutil.net_io_counters(pernic=True)

        if interface_name not in stats:
            print(f"No se encontró la interfaz: {interface_name}. Reintentando en 1 segundo...")
            time.sleep(1)
            continue
        else:
            data = stats[interface_name]
            latencia = obtener_latencia(gateway)

            fila = [
                # time.strftime("%Y-%m-%d %H:%M:%S"),
                data.bytes_sent,
                data.bytes_recv,
                data.packets_sent,
                data.packets_recv,
                latencia
            ]

            if latencia > 4 and latencia != 9999:
                with open(archivo, mode='a', newline='') as f:
                    escritor = csv.writer(f)
                    escritor.writerow(fila)

                print(f"Datos guardados: {fila}")
            else:
                print(f"Registro descartado: {fila}")
        
            time.sleep(intervalo)


if __name__ == "__main__":
    registrar_datos(interface_name="Wi-Fi", intervalo=1)
