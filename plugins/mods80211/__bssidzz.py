#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import logging
import re
from sqlalchemy import MetaData, Table, Column, String, Integer, DateTime
from includes.common import snoop_hash
logging.getLogger("scapy.runtime").setLevel(logging.ERROR)
from scapy.all import Dot11Beacon, Dot11Elt
import datetime
from includes.fonts import *
import os

class Snarf():
    """Calculates proximity observations of devices based on probe-requests emitted."""

    DELTA_PROX = 300
    """Proximity session duration, before starting a new one."""

    #def __init__(self,hash_macs="False"):
    def __init__(self, **kwargs):
        self.current_proximity_sessions = {}
        self.closed_proximity_sessions = collections.deque()
        self.MOST_RECENT_TIME = 0
        #self.hash_macs = hash_macs

        self.hash_macs = kwargs.get('hash_macs', False)
        #self.drone = kwargs.get('drone',"no_drone_name_supplied")
        #self.run_id = kwargs.get('run_id', "no_run_id_supplied")
        #self.location = kwargs.get('location', "no_location_supplied")
        self.verb = kwargs.get('verbose', 0)
        self.fname = os.path.splitext(os.path.basename(__file__))[0]

    @staticmethod
    def get_tables():
        """Make sure to define your table here"""
        table = Table('access_points', MetaData(),
                      Column('mac', String(64), primary_key=True), #Len 64 for sha256
                      Column('first_obs', DateTime, primary_key=True, autoincrement=False),
                      Column('ssid', String(64)),
                      Column('last_obs', DateTime),
                      Column('sunc', Integer, default=0),
                      #Column('location', String(length=60)),
                      #Column('drone', String(length=20), primary_key=True)
                    )

        return [table]

    def proc_packet(self,p):
        self.MOST_RECENT_TIME = int(p.time)
        if not p.haslayer(Dot11Beacon):
            return
        mac = re.sub(':', '', p.addr2)
        if self.hash_macs == "True":
            mac = snoop_hash(mac)
        t = int(p.time)
        if p[Dot11Elt].info != '':
            ssid = p[Dot11Elt].info.decode('utf-8', 'ignore')
        
        try:
            sig_str = -(256-ord(p.notdecoded[-4:-3])) #TODO: Use signal strength
        except:
            logging.error("Unable to extract signal strength")
            logging.error(p.summary())
        # New
        if mac not in self.current_proximity_sessions:
            self.current_proximity_sessions[(mac,ssid)] = [t, t, 1, 0]
            if self.verb > 0:
                logging.info("Sub-plugin %s%s%s observed new device: %s%s%s" % (GR,self.fname,G,GR,mac, G))
        else:
            #Check if expired
            self.current_proximity_sessions[(mac,ssid)][2] += 1 #num_probes counter
            first_obs = self.current_proximity_sessions[(mac,ssid)][0]
            last_obs = self.current_proximity_sessions[(mac,ssid)][1]
            num_probes = self.current_proximity_sessions[(mac,ssid)][2]
            if (t - last_obs) >= self.DELTA_PROX:
                self.closed_proximity_sessions.append((mac, ssid, first_obs, last_obs, num_probes)) #Terminate old prox session
                self.current_proximity_sessions[(mac,ssid)] = [t, t, 1, 0] #Create new prox session
            else:
                self.current_proximity_sessions[(mac,ssid)][1] = t
                self.current_proximity_sessions[(mac,ssid)][3] = 0 #Mark as require db sync

    def get_data(self):
        """Ensure data is returned in the form (tableName,[colname:data,colname:data]) """

        # First check if expired, if so, move to closed
        # Use the most recent packet received as a timestamp. This may be more useful than taking
        #  the system time as we can parse pcaps.
        todel=[]
        data=[] 
        for mac,v in self.current_proximity_sessions.iteritems():
            first_obs=v[0]
            last_obs=v[1]
            num_probes=v[2]
            t=self.MOST_RECENT_TIME
            if(t - last_obs >= self.DELTA_PROX):
                self.closed_proximity_sessions.append((mac,ssid,first_obs,t,num_probes))
                todel.append((mac,ssid))
        for mac in todel:
            del(self.current_proximity_sessions[(mac,ssid)])
        #1. Open Prox Sessions
        tmp_open_prox_sessions=[]  
        for macssid,v in self.current_proximity_sessions.iteritems():
            mac,ssid=macssid
            first_obs,last_obs,num_probes=v[0],v[1],v[2]
            first_obs,last_obs = datetime.datetime.fromtimestamp(first_obs), datetime.datetime.fromtimestamp(last_obs)
            if v[3] == 0:
                tmp_open_prox_sessions.append({"mac":mac,"ssid":ssid,"first_obs":first_obs,"last_obs":last_obs,"num_probes":num_probes})#, "drone":self.drone, "location":self.location})
        #2. Closed Prox Sessions
        tmp_closed_prox_sessions=[] 
        for i in range(len(self.closed_proximity_sessions)):
            macssid,first_obs,last_obs,num_probes=self.closed_proximity_sessions.popleft()
            mac,ssid=macssid
            first_obs,last_obs = datetime.datetime.fromtimestamp(first_obs), datetime.datetime.fromtimestamp(last_obs)
            tmp_closed_prox_sessions.append( {"mac":mac,"ssid":ssid,"first_obs":first_obs,"last_obs":last_obs,"num_probes":num_probes})#, "drone":self.drone, "location":self.location} )
        if( len(tmp_open_prox_sessions+tmp_closed_prox_sessions) > 0 ):
            #data.append(   (table,columns,tmp+tmp2)    )
            #Set flag to indicate data has been fetched:
            for i in tmp_open_prox_sessions:
                mac=i['mac']    
                self.current_proximity_sessions[(mac,ssid)][3]=1 #Mark it has having been retrieved, so we don't resend until it changes

            #return None
            return ("access_points",tmp_open_prox_sessions+tmp_closed_prox_sessions)
