from ryu.base import app_manager                                     # type: ignore
from ryu.controller import ofp_event                                 # type: ignore
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls       # type: ignore
from ryu.lib import hub                                              # type: ignore
from ryu.ofproto import ofproto_v1_3                                 # type: ignore
from ryu.lib.packet import packet, ethernet                          # type: ignore

import time
import itertools
import joblib
import numpy as np


class LoadBalancerQoS:
    def __init__(self):
        self.port_iterator = {}
        self.metrics = {"switches": {}, "notifications": []}
        self.echo_timestamps = {}
        self.model = joblib.load("traffic_predictor.pkl")

    def predict_congestion(self, features):
        features = np.array(features).reshape(1, -1)
        return self.model.predict(features)[0]

    def balancear_trafico(self, datapath, dst):
        dpid = datapath.id
        ofproto = datapath.ofproto

        if dpid not in self.metrics["switches"]:
            if dpid not in self.port_iterator:
                self.port_iterator[dpid] = itertools.cycle(
                    port for port in range(1, 50)
                    if port not in [ofproto.OFPP_FLOOD, ofproto.OFPP_CONTROLLER]
                )
            return next(self.port_iterator[dpid])

        puertos_estadisticas = self.metrics["switches"].get(dpid, {})

        traffic_features = []
        for port, data in puertos_estadisticas.items():
            tx = data.get("tx_bytes", 0)
            rx = data.get("rx_bytes", 0)
            txp = data.get("tx_packets", 0)
            rxp = data.get("rx_packets", 0)
            lat = data.get("latency", 0)
            traffic_features.extend([tx, rx, txp, rxp, lat])

        if not traffic_features:
            return ofproto.OFPP_CONTROLLER

        congestion = self.predict_congestion(traffic_features)

        if congestion:
            self._apply_qos(datapath, {}, 10, queue_id=1)
            return p

        puerto_seleccionado = min(
            puertos_estadisticas.items(),
            key=lambda item: item[1].get("tx_bytes", float('inf')),
            default=(ofproto.OFPP_FLOOD, {})
        )[0]

        return puerto_seleccionado if puerto_seleccionado != ofproto.OFPP_FLOOD else ofproto.OFPP_CONTROLLER

    def _apply_qos(self, datapath, match_fields, priority, queue_id):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        match = parser.OFPMatch(**match_fields)
        actions = [
            parser.OFPActionSetQueue(queue_id),
            parser.OFPActionOutput(ofproto.OFPP_NORMAL)
        ]
        instructions = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS, actions)]
        flow_mod = parser.OFPFlowMod(
            datapath=datapath,
            priority=priority,
            match=match,
            instructions=instructions
        )

        datapath.send_msg(flow_mod)

        timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        switch_id = datapath.id
        notification = {
            "timestamp": timestamp,
            "title": "Política de QoS aplicada",
            "subtitle": f"Switch {switch_id}, Cola {queue_id}",
            "description": f"QoS aplicado con prioridad {priority} al tráfico que coincide con {match_fields or 'cualquier tráfico'}."
        }
        self.metrics["notifications"].append(notification)
        return queue_id

    def enviar_echo_request(self, datapath):
        parser = datapath.ofproto_parser
        self.echo_timestamps[datapath.id] = time.time()
        echo_req = parser.OFPEchoRequest(datapath, data=b"latency_check")
        datapath.send_msg(echo_req)

    def actualizar_latencia(self, dpid, latency):
        if dpid in self.metrics["switches"]:
            for port in self.metrics["switches"][dpid]:
                self.metrics["switches"][dpid][port]["latency"] = latency

