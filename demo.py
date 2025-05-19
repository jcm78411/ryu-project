from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.controller.handler import CONFIG_DISPATCHER

class PortStatsMonitor(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super(PortStatsMonitor, self).__init__(*args, **kwargs)
        self.datapaths = {}

    @set_ev_cls(ofp_event.EventOFPStateChange, [MAIN_DISPATCHER, CONFIG_DISPATCHER])
    def _state_change_handler(self, ev):
        datapath = ev.datapath
        if ev.state == MAIN_DISPATCHER:
            self.datapaths[datapath.id] = datapath
            self.request_port_stats(datapath)

    def request_port_stats(self, datapath):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        req = parser.OFPPortStatsRequest(datapath, 0, ofproto.OFPP_ANY)
        datapath.send_msg(req)









    @set_ev_cls(ofp_event.EventOFPPortStatsReply, 
                MAIN_DISPATCHER)
    def port_stats_reply_handler(self, ev):
        body = ev.msg.body
        for stat in body:
            self.logger.info(
                'Port %d: ' \
                'RX Packets=%d, ' \
                'TX Packets=%d, ' \
                'RX Bytes=%d, ' \
                'TX Bytes=%d',
                stat.port_no, 
                stat.rx_packets, 
                stat.tx_packets, 
                stat.rx_bytes, 
                stat.tx_bytes
            )
