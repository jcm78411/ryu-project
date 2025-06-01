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
        self.metrics = {
            "switches": {},
            "switch_latency": {},
            "cpu": 0,
            "memory": 0
        }
        self.echo_timestamps = {}
        self.rr_index = {}  # Para balanceo Round Robin por switch

        # Lanzar hilo de monitoreo de CPU/Memoria
        self.monitor_thread = threading.Thread(target=self._monitor_loop)
        self.monitor_thread.daemon = True
        self.monitor_thread.start()

    def _monitor_loop(self):
        while True:
            self._log_system_stats()
            time.sleep(2)  # cada 2 segundos

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

        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

        self.request_port_stats(datapath)
        self.send_echo_request(datapath)

    def add_flow(self, datapath, priority, match, actions):
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        mod = parser.OFPFlowMod(datapath=datapath, priority=priority,
                                match=match, instructions=inst)
        datapath.send_msg(mod)

    def request_port_stats(self, datapath):
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, datapath.ofproto.OFPP_ANY)
        datapath.send_msg(req)

    def send_echo_request(self, datapath):
        self.echo_timestamps[datapath.id] = time.time()
        echo_req = datapath.ofproto_parser.OFPEchoRequest(datapath, data=b'ping')
        datapath.send_msg(echo_req)

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
        self.metrics["switches"].setdefault(dpid, {})

        valid_ports = []
        for stat in ev.msg.body:
            port_no = stat.port_no
            if port_no == ev.msg.datapath.ofproto.OFPP_LOCAL or port_no == 4294967294:
                continue
            valid_ports.append(port_no)

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

            self.logger.info("Switch %s Port %s - TX: %d bytes, RX: %d bytes, CPU: %.2f%%, MEM: %.2f%%",
                             dpid, port_no, stat.tx_bytes, stat.rx_bytes,
                             self.metrics["cpu"], self.metrics["memory"])
        if dpid not in self.rr_index:
            self.rr_index[dpid] = {"index": 0, "ports": valid_ports}
        else:
            self.rr_index[dpid]["ports"] = valid_ports

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        msg = ev.msg
        datapath = msg.datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto
        dpid = datapath.id

        pkt = packet.Packet(msg.data)
        eth_pkt = pkt.get_protocol(ethernet.ethernet)
        dst = eth_pkt.dst
        src = eth_pkt.src

        in_port = msg.match['in_port']
        self.logger.info("packet in %s %s %s %s", dpid, src, dst, in_port)

        # Balanceo de carga estático Round Robin
        rr_info = self.rr_index.get(dpid)
        if not rr_info or not rr_info["ports"]:
            self.logger.warning("No hay puertos válidos para balanceo en el switch %s", dpid)
            return

        ports = rr_info["ports"]
        out_port = ports[rr_info["index"] % len(ports)]
        rr_info["index"] += 1

        # Evitar que reenvíe al mismo puerto por donde llegó
        if out_port == in_port:
            out_port = ports[(rr_info["index"] % len(ports))]
            rr_info["index"] += 1

        actions = [parser.OFPActionOutput(out_port)]

        # Opcional: instalar flujo si no es broadcast
        match = parser.OFPMatch(in_port=in_port, eth_dst=dst)
        self.add_flow(datapath, 1, match, actions)

        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=ofproto.OFP_NO_BUFFER,
            in_port=in_port,
            actions=actions,
            data=msg.data
        )
        datapath.send_msg(out)
