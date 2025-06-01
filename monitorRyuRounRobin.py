import time
import threading
import random
import psutil
import csv
import os
from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet, ethernet

class ExampleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(ExampleSwitch13, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.rr_index = {}  # Para balanceo Round Robin por switch
        self.metrics = {
            "switches": {},
            "switch_latency": {},
            "cpu": 0,
            "memory": 0
        }
        self.echo_timestamps = {}

        # Lanzar hilo de monitoreo de CPU/Memoria
        self.stats_thread = threading.Thread(target=self._stats_loop)
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def _monitor_loop(self):
        while True:
            self._log_system_stats()
            time.sleep(2)  # cada 2 segundos
    def _stats_loop(self):
        while True:
            for dp in list(self.mac_to_port.keys()):
                self.request_port_stats(dp)
                self.send_echo_request(dp)
            time.sleep(2)

    def _log_system_stats(self):
        cpu_usage = psutil.cpu_percent()
        memory_info = psutil.virtual_memory()
        self.metrics["cpu"] = cpu_usage
        self.metrics["memory"] = memory_info.percent

        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        rows = []

        for dpid, ports in self.metrics["switches"].items():
            for port_no, data in ports.items():
                row = {
                    "timestamp": timestamp,
                    "switch_id": dpid,
                    "port": port_no,
                    "tx_bytes": data.get("tx_bytes", 0),
                    "rx_bytes": data.get("rx_bytes", 0),
                    "tx_packets": data.get("tx_packets", 0),
                    "rx_packets": data.get("rx_packets", 0),
                    "latency": data.get("latency", 0),
                    "switch_latency": self.metrics["switch_latency"].get(dpid, 0),
                    "cpu_usage": cpu_usage,
                    "mem_usage": memory_info.percent
                }
                rows.append(row)

        if rows:
            self._append_to_csv(rows)

    def _append_to_csv(self, rows):
        file_path = "metrics_log_rr.csv"
        max_lines = 194375

        # Verifica si el archivo existe y cuenta las líneas
        file_exists = os.path.isfile(file_path)
        current_line_count = 0

        if file_exists:
            with open(file_path, 'r') as f:
                current_line_count = sum(1 for _ in f)

        # Si ya se alcanzó o superó el límite, no escribir más
        if current_line_count >= max_lines:
            self.logger.warning("Límite de %d líneas alcanzado en %s. No se escribirán más datos.", max_lines, file_path)
            return

        with open(file_path, mode='a', newline='') as csvfile:
            fieldnames = [
                "timestamp",
                "switch_id",
                "port",
                "tx_bytes",
                "rx_bytes",
                "tx_packets",
                "rx_packets",
                "latency",
                "switch_latency",
                "cpu_usage",
                "mem_usage"
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

            if not file_exists:
                writer.writeheader()
                current_line_count += 1

            # Escribe solo si no excede el máximo
            for row in rows:
                if current_line_count >= max_lines:
                    self.logger.warning("Límite de líneas alcanzado mientras escribía. Se detiene el guardado.")
                    break
                writer.writerow(row)
                current_line_count += 1

    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self.mac_to_port[datapath.id] = {}  # ✅ Diccionario para mapear MACs a puertos

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        self.request_port_stats(datapath)
        self.send_echo_request(datapath)

    def add_flow(self, datapath, priority, match, actions, idle_timeout=0, hard_timeout=0):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst,
                                idle_timeout=idle_timeout, hard_timeout=hard_timeout)
        datapath.send_msg(mod)

    def request_port_stats(self, datapath):
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY)
        datapath.send_msg(req)

    def send_echo_request(self, datapath):
        self.echo_timestamps[datapath.id] = time.time()
        echo_req = datapath.ofproto_parser.OFPEchoRequest(datapath, data=b'ping')
        datapath.send_msg(echo_req)

    def balancear_trafico(self, datapath, dst_mac, in_port):
        dpid = datapath.id
        ofproto = datapath.ofproto

        rr_data = self.rr_index.get(dpid)
        if not rr_data or not rr_data.get("ports"):
            self.logger.warning(f"[RR] No hay puertos disponibles para DPID {dpid}")
            return None

        ports_disponibles = [p for p in rr_data["ports"] if p != in_port and p != ofproto.OFPP_LOCAL]

        if not ports_disponibles:
            self.logger.warning(f"[RR] No hay puertos válidos para balanceo en DPID {dpid}")
            return None

        index = rr_data["index"] % len(ports_disponibles)
        out_port = ports_disponibles[index]
        self.rr_index[dpid]["index"] += 1

        self.logger.info(f"[RR] DPID {dpid}: puerto seleccionado para {dst_mac} es {out_port}")
        return out_port


    @set_ev_cls(ofp_event.EventOFPEchoReply, MAIN_DISPATCHER)
    def echo_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        latency = time.time() - self.echo_timestamps.get(dpid, time.time())
        self.metrics["switch_latency"][dpid] = latency
        self.logger.info("Latencia del switch %s: %.2f ms", dpid, latency * 1000)

    def actualizar_latencia(self, dpid):
        latency = random.uniform(1, 600)
        if dpid in self.metrics["switches"]:
            for port in self.metrics["switches"][dpid].values():
                port["latency"] = latency
        return int(latency)

    @set_ev_cls(ofp_event.EventOFPPortStatsReply, MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        dpid = ev.msg.datapath.id
        ofproto = ev.msg.datapath.ofproto
        self.metrics["switches"].setdefault(dpid, {})
        valid_ports = []

        for stat in ev.msg.body:
            port_no = stat.port_no

            # Ignorar puertos inválidos o especiales
            if port_no >= ofproto.OFPP_MAX or port_no == 4294967294:
                continue

            self.metrics["switches"][dpid][port_no] = {
                "switch_id": dpid,
                "port": port_no,
                "tx_bytes": stat.tx_bytes,
                "rx_bytes": stat.rx_bytes,
                "tx_packets": stat.tx_packets,
                "rx_packets": stat.rx_packets,
                "latency": self.actualizar_latencia(dpid),
                "switch_latency": self.metrics["switch_latency"].get(dpid, 0),
                "cpu_usage": self.metrics["cpu"],
                "mem_usage": self.metrics["memory"]
            }
            valid_ports.append(port_no)

        # Actualiza o inicializa lista y contador de puertos para balanceo round robin
        if valid_ports:
            if dpid not in self.rr_index:
                self.rr_index[dpid] = {"ports": valid_ports, "index": 0}
            else:
                self.rr_index[dpid]["ports"] = valid_ports

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        self.logger.info("\n[DEBUG] Entró al handler PacketIn")
        
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

        src = eth_pkt.src
        dst = eth_pkt.dst
        in_port = msg.match['in_port']

        self.logger.info("Packet in: DPID=%s, SRC=%s, DST=%s, IN_PORT=%s", dpid, src, dst, in_port)

        # Aprender dirección MAC del origen
        self.mac_to_port[dpid][src] = in_port

        # Determinar puerto de salida
        out_port = self.mac_to_port[dpid].get(dst)

        if out_port is None:
            self.logger.info(f"[RR] Puerto de salida para {dst} desconocido, usando Round Robin")
            self.send_echo_request(datapath)
            out_port = self.balancear_trafico(datapath, dst, in_port)

            if out_port is None:
                self.logger.info(f"[RR] balancear_trafico no devolvió puerto → usando FLOOD")
                out_port = ofproto.OFPP_FLOOD

        if out_port != ofproto.OFPP_FLOOD:
            # Instalar flujo solo si es puerto válido, con timeout para que expire
            match = parser.OFPMatch(in_port=in_port, eth_src=src, eth_dst=dst)
            actions = [parser.OFPActionOutput(out_port)]
            self.add_flow(datapath, 1, match, actions, idle_timeout=5, hard_timeout=10)
            self.logger.info(f"[FLOW] Instalado flujo {src} → {dst} por puerto {out_port} con timeouts")
        else:
            actions = [parser.OFPActionOutput(ofproto.OFPP_FLOOD)]
            self.logger.info(f"[FLOOD] FLOOD para {dst}")

        # Enviar paquete de salida
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=in_port,
            actions=actions,
            data=msg.data if msg.buffer_id == ofproto.OFP_NO_BUFFER else None
        )
        datapath.send_msg(out)
