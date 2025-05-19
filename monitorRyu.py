from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet, arp, ipv4
from ryu.lib import hub
import itertools
import psutil
import logging
import time
import threading
from flask import Flask, jsonify
import joblib
import numpy as np
import csv
import os
from threading import Lock

# ------------------------- Clase LoadBalancerQoS Integrada -------------------------
class LoadBalancerQoS:
    def __init__(self, metrics):
        self.port_iterator = {}
        self.metrics = metrics  # Usamos los mismos metrics que el controlador
        self.echo_timestamps = {}
        self.model = joblib.load("predictor.pkl")

    def predict_congestion(self, features):
        features = np.array(features).reshape(1, -1)
        return self.model.predict(features)[0]

    def actualizar_latencia(self, dpid):
        latency = 0
        if switch := self.metrics["switches"].get(dpid):
            for port in switch.values():
                port["latency"] = latency


    def balancear_trafico(self, datapath, dst):
        dpid = datapath.id
        ofproto = datapath.ofproto

        # Si no hay estadísticas, usar round-robin
        if dpid not in self.metrics["switches"]:
            if dpid not in self.port_iterator:
                self.port_iterator[dpid] = itertools.cycle(
                    port for port in range(1, 50)
                )
            return next(self.port_iterator[dpid])
      
        puertos_estadisticas = self.metrics["switches"].get(dpid, {})
        traffic_features = []
        
        latency = self.actualizar_latencia(dpid)
        # tx_bytes,rx_bytes,tx_packets,rx_packets,latency,congestion
        for port, data in puertos_estadisticas.items():
            tx_bytes = data.get("tx_bytes", 0)
            rx_bytes = data.get("rx_bytes", 0)
            tx_packets = data.get("tx_packets", 0)
            rx_packets = data.get("rx_packets", 0)
            latency = int(data.get("latency", 0))

            # Concatenar métricas por puerto al vector de características
            traffic_features.extend([
                tx_bytes,
                rx_bytes,
                tx_packets,
                rx_packets,
                latency
            ])

        # Paso 1: Predicción con modelo (puede ser una función de ML o heurística)
        if self.predict_congestion(traffic_features):
            print("="*100)
            print("="*100)
            print("="*100)

            print(traffic_features)

            print("="*100)
            print("="*100)
            print("="*100)

            # Aplicar QoS si hay congestión
            return self._apply_qos(datapath, {}, 10, queue_id=1)

        # Paso 2: Elegir el puerto con menos carga actual (bytes transmitidos recientemente)
        puerto_optimo = min(
            puertos_estadisticas.items(),
            key=lambda item: item[1].get("tx_bytes", float('inf')),
            default=(ofproto.OFPP_FLOOD, {})
        )[0]

        return puerto_optimo

    def _apply_qos(self, datapath, match_fields, priority, queue_id):
        
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        # Crear regla de flujo con cola preconfigurada
        actions = [
            parser.OFPActionSetQueue(queue_id),
            parser.OFPActionOutput(ofproto.OFPP_NORMAL)
        ]

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]

        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=parser.OFPMatch(**match_fields),
            instructions=inst
        )
        datapath.send_msg(flow_mod)

        # Limitar notificaciones a los últimos 10 elementos
        notification = {
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "title": f"QoS: Cola {queue_id}",
            "description": f"Tráfico asignado a cola {queue_id}"
        }
        self.metrics["notifications"] = (self.metrics["notifications"] + [notification])[-10:]

        return queue_id


    def enviar_echo_request(self, datapath):
        parser = datapath.ofproto_parser
        self.echo_timestamps[datapath.id] = time.time()
        echo_req = parser.OFPEchoRequest(datapath, data=b"latency_check")
        datapath.send_msg(echo_req)
        

# ------------------------- Controlador Principal Modificado -------------------------
class RyuManagerCustomSDN(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.datapaths = {}
        self.metrics = {
            "cpu": 0,
            "memory": 0,
            "switches": {},
            "devices": [],
            "notifications": []
        }
        
        self.csv_lock = Lock()  # Lock para escritura segura en CSV
        self.csv_filename = "traffic_metrics.csv"
        self._init_csv_file()  # Inicializar archivo CSV
        
        self.load_balancer = LoadBalancerQoS(self.metrics)  # Inicialización integrada
        hub.spawn(self._monitor)
        threading.Thread(target=self.start_http_server, daemon=True).start()
    
    def _init_csv_file(self):
        """Crear archivo CSV con encabezados si no existe"""
        if not os.path.exists(self.csv_filename):
            with open(self.csv_filename, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    #'timestamp', 
                    #'switch_id', 
                    #'port', 
                    #'tx_rate',
                    #'rx_rate',
                    'tx_bytes', 
                    'rx_bytes', 
                    'tx_packets', 
                    'rx_packets',
                    'latency',
                    #'cpu_usage', 
                    #'mem_usage', 
                    #'dst_ip',
                    #'qos_queue', 
                    #'predicted_congestion'
                ])
    
    def _log_traffic_data(self, dpid, port_stats, dst_ip=None):
        """Registrar métricas en archivo CSV"""
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
        
        with self.csv_lock:  # Bloqueo para escritura segura
            with open(self.csv_filename, 'a', newline='') as f:
                writer = csv.writer(f)
                
                latencya = self.load_balancer.actualizar_latencia(dpid)
                for port, stats in port_stats.items():
                    # Calcular valores relevantes  
                    tx_rate = stats.get('tx_bytes', 0) / 1024
                    rx_rate = stats.get('rx_bytes', 0) / 1024
                    tx_bytes = stats.get("tx_bytes", 0)
                    rx_bytes = stats.get("rx_bytes", 0)
                    tx_packets = stats.get("tx_packets", 0)
                    rx_packets = stats.get("rx_packets", 0)
                    latency = int(stats.get("latency", 0))
                    
                    writer.writerow([
                        #timestamp,
                        #dpid,
                        #port,
                        #f"{tx_rate:.2f}",
                        #f"{rx_rate:.2f}",
                        f"{tx_bytes}",
                        f"{rx_bytes}",
                        f"{tx_packets}",
                        f"{rx_packets}",
                        f"{latency:.2f}",
                        #self.metrics['cpu'],
                        #self.metrics['memory'],
                        #dst_ip or 'N/A',
                        #stats.get('qos_queue', 'N/A'),
                        #stats.get('congestion_prediction', 'N/A')
                    ])
                    
    def start_http_server(self):
        try:
            app = Flask(__name__)
            @app.route('/metrics')
            def get_metrics():
                return jsonify({
                    k: v for k, v in self.metrics.items()
                    if k != "qos_configured"  # Excluir datos internos
                })
            app.run(host='0.0.0.0', port=5000)
        except Exception as e:
            self.logger.error("Error en servidor HTTP: %s", str(e))
            
    def _monitor(self):
        while True:
            for dp in self.datapaths.values():
                self._request_stats(dp)
            self._log_system_stats()
            self._calculate_bandwidth()
            
            for dpid, port_stats in self.metrics["switches"].items():
                self._log_traffic_data(dpid, port_stats)
                
            hub.sleep(2)

    def _log_system_stats(self):
        cpu_usage = psutil.cpu_percent()
        memory_info = psutil.virtual_memory()
        self.metrics["cpu"] = cpu_usage
        self.metrics["memory"] = memory_info.percent
        self.logger.info('CPU Usage: %s%%', cpu_usage)
        self.logger.info('Memory Usage: %s%% (%s MB used)', memory_info.percent, memory_info.used / (1024 ** 2))

    def _request_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)

    def _calculate_bandwidth(self):
        for switch_id, ports in self.metrics["switches"].items():
            for port_no, stats in ports.items():
                tx_bytes = stats.get("tx_bytes", 0)
                rx_bytes = stats.get("rx_bytes", 0)

                bandwidth = (tx_bytes + rx_bytes) * 8
                bandwidth_mbps = round((bandwidth / 1024 / 1024), 2)

                for device in self.metrics["devices"]:
                    if device["switch"] == f"{str(switch_id)}" and device["port"] == str(port_no):
                        device["band"] = bandwidth_mbps
                        self.logger.info(
                            "Ancho de banda actualizado: switch=%s, puerto=%s, banda=%s Mbps",
                            switch_id, port_no, bandwidth_mbps
                        )

    @set_ev_cls(ofp_event.EventOFPStateChange, [CONFIG_DISPATCHER, MAIN_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
            self.logger.info("Switch %s conectado", datapath.id)
        elif ev.state == 'DEAD_DISPATCHER':
            if datapath.id in self.datapaths:
                del self.datapaths[datapath.id]
                self.logger.info("Switch %s desconectado", datapath.id)

    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        # Cálculo de latencia
        dpid = ev.msg.datapath.id
        latency = time.time() - self.load_balancer.echo_timestamps.get(dpid, time.time())
        self.load_balancer.actualizar_latencia(dpid, latency)
        self.logger.info("Latencia actualizada: Switch %s - %.2f ms", dpid, latency*1000)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)

        if eth_pkt is None:
            return

        dst = eth_pkt.dst
        src = eth_pkt.src

        in_port = msg.match['in_port']
        self.logger.info("Packet in: DPID=%s, SRC=%s, DST=%s, IN_PORT=%s", dpid, src, dst, in_port)

        if not eth_pkt.dst.startswith("ff:ff:ff:ff:ff:ff"):
            self._register_device(dpid, in_port, eth_pkt.src, pkt)

        self.mac_to_port[dpid][src] = in_port

        out_port = self.load_balancer.balancear_trafico(datapath, dst)

        actions = [parser.OFPActionOutput(out_port)]

        if out_port != ofproto.OFPP_FLOOD:
            match = parser.OFPMatch(in_port=in_port, eth_dst=dst, eth_src=src)
            self.add_flow(datapath, 1, match, actions)

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        datapath.send_msg(out)
        
        # Obtener IP destino si existe
        dst_ip = 'N/A'
        ip_pkt = pkt.get_protocol(ipv4.ipv4)
        if ip_pkt:
            dst_ip = ip_pkt.dst
        
        # Registrar en CSV con contexto de paquete
        self._log_traffic_data(
            dpid=dpid,
            port_stats=self.metrics["switches"].get(dpid, {}),
            dst_ip=dst_ip
        )

    def _register_device(self, dpid, port, mac, pkt):
        # Corrección para IPv4 (src_ip en lugar de src)
        ip = None
        for p in pkt.protocols:
            if isinstance(p, arp.arp):
                ip = p.src_ip
            elif isinstance(p, ipv4.ipv4):
                ip = p.src_ip  # Corrección clave aquí
            
        if ip:
            self.metrics["devices"].append({
                "ip": ip,
                "mac": mac,
                "switch": str(dpid),
                "port": str(port),
                "band": 0.0
            })

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        self.add_table_miss_flow(datapath)
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        
        
        self.load_balancer._apply_qos(datapath=datapath, match_fields={}, priority=1, queue_id=0)

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)
        
    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        body = ev.msg.body
        dpid = ev.msg.datapath.id

        # Asegurar estructuras de almacenamiento
        switch_stats = self.metrics.setdefault("switches", {})
        port_data = switch_stats.setdefault(dpid, {})

        for stat in body:
            port_no = stat.port_no
            port_stats = port_data.setdefault(port_no, {})

            # Calcular diferencias desde la última medición
            tx_bytes_prev = port_stats.get("tx_bytes", 0)
            rx_bytes_prev = port_stats.get("rx_bytes", 0)
            tx_pkts_prev = port_stats.get("tx_packets", 0)
            rx_pkts_prev = port_stats.get("rx_packets", 0)

            # Diferencias (delta) para monitoreo reciente
            tx_bytes_diff = stat.tx_bytes - tx_bytes_prev
            rx_bytes_diff = stat.rx_bytes - rx_bytes_prev
            tx_pkts_diff = stat.tx_packets - tx_pkts_prev
            rx_pkts_diff = stat.rx_packets - rx_pkts_prev

            # Guardar los nuevos valores acumulados
            port_stats.update({
                "tx_bytes": stat.tx_bytes,
                "rx_bytes": stat.rx_bytes,
                "tx_packets": stat.tx_packets,
                "rx_packets": stat.rx_packets,
                "delta_tx_bytes": tx_bytes_diff,
                "delta_rx_bytes": rx_bytes_diff,
                "delta_tx_packets": tx_pkts_diff,
                "delta_rx_packets": rx_pkts_diff,
            })

            # Log (opcional)
            self.logger.info(
                "Switch %s, Port %s - TX: %d bytes (%d pkts), RX: %d bytes (%d pkts)",
                dpid, port_no,
                tx_bytes_diff, tx_pkts_diff,
                rx_bytes_diff, rx_pkts_diff
            )

    def add_table_miss_flow(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch()  # Sin coincidencia, captura todo.
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER, ofproto.OFPCML_NO_BUFFER)]
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=0,
            match=match,
            instructions=inst
        )
        datapath.send_msg(mod)
