#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
    SleekXMPP: The Sleek XMPP Library
    Copyright (C) 2010  Nathanael C. Fritz,
                  2017  Mario Hock
    This file is part of SleekXMPP.

    See the file LICENSE for copying permission.
"""

import sys
import os
import logging
import getpass
from optparse import OptionParser
import time
import json

import sleekxmpp

# Python versions before 3.0 do not use UTF-8 encoding
# by default. To ensure that Unicode is handled properly
# throughout SleekXMPP, we will set the default encoding
# ourselves to UTF-8.
if sys.version_info < (3, 0):
    from sleekxmpp.util.misc_ops import setdefaultencoding
    setdefaultencoding('utf8')
else:
    raw_input = input



## NOTE: Deceide whether we want to handle a single account or all accounts here...
class Config:
    def __init__(self, path):
        self.path = path
        
        self._accounts = None
        self._data = {}
        
        self._load()
        
        
    def _load(self):
        with open(self.path + "/accounts.json", "r") as f:
            self._accounts = json.load(f)
            
        ## data
        try:
            with open(self.path + "/" + self.get_jid() + ".json", "r") as f:
                self._data = json.load(f)
        except FileNotFoundError as e:
            print( "No data stored for: '{}'".format(self.get_jid()) )
            
        #print("Last message: {}".format(self.get_last_message()))
        
        
    ## accounts are read-only (at the moment..?)
    #def store(self):
        #with open(self.path + "/accounts.json", "w") as f:
            #json.dump(self._accounts, f, sort_keys=True, indent=4)

    def store_data(self):
        #print("Store: {}".format(json.dumps(self._data, sort_keys=True, indent=4)))
        with open(self.path + "/" + self.get_jid() + ".json", "w") as f:
            json.dump(self._data, f, sort_keys=True, indent=4)

    def get_jid(self):
        return self._accounts["Accounts"][0]["jid"]
    
    def get_password(self):
        return self._accounts["Accounts"][0]["password"]
    
    def set_last_message(self, id):
        if id:
            self._data["last-message"] = id
            self.store_data()
        
    def get_last_message(self):
        return self._data.get("last-message")
    
    
    

class HistoryAlert(sleekxmpp.ClientXMPP):

    def __init__(self, jid, password, config):
        sleekxmpp.ClientXMPP.__init__(self, jid, password)

        self._jid = jid
        self._config = config

        self.id_of_last_message = config.get_last_message()


        # The session_start event will be triggered when
        # the bot establishes its connection with the server
        # and the XML streams are ready for use. We want to
        # listen for this event so that we we can initialize
        # our roster.
        self.add_event_handler("session_start", self.start)

        # The message event is triggered whenever a message
        # stanza is received. Be aware that that includes
        # MUC messages and error messages.
        self.add_event_handler("message", self.message)

    def start(self, event):
        """
        Process the session_start event.

        Typical actions for the session_start event are
        requesting the roster and broadcasting an initial
        presence stanza.

        Arguments:
            event -- An empty dictionary. The session_start
                     event does not provide any additional
                     data.
        """
        self.send_presence()
        self.get_roster()

        ## TODO optional.. maybe just check if preference is set to "none"
        ret = self["xep_0313"].get_preferences()
        print("Archiving default is: ", ret["mam_prefs"]["default"])
        # self["xep_0313"].set_preferences(default="always", block=True)
        
        self.get_history()
        
        try:
            ## program regular callback, just in case we missed a message somehow..
            self["xep_0313"].xmpp.schedule('Re-check Timer',
                        300,
                        self._timer_callback,
                        repeat=True)
        except ValueError:
            print("/// Timer already active.")
            
        #self.xmpp.scheduler.remove('Ping keepalive')

    ## check history in regular intervals; just in case..
    def _timer_callback(self):
        self.get_history(quiet=True)
            

    def get_history(self, quiet=False):
        #print("Start MAM")

        # async non-blocking
        # answer = self["xep_0313"].retrieve(block=False, callback=self.__handle_mam_result)

        if not quiet:
            print("checking messages...")
            
        # blocking
        try:
            answer = self["xep_0313"].retrieve(block=True, timeout=10, callback=None,
                                            continue_after=self.id_of_last_message,
                                            collect_all=True)


            ## TODO set a timeout and try to reconnect if timeout reached..
            #   see ping.py  -->  self.xmpp.reconnect()

            # If no callback is used, the handler function is called here to
            # display the results.
            if not quiet:
                self.__handle_mam_result_verbose(answer)
            else:
                self.__handle_mam_result(answer)

            print( "==== {} ====".format(time.strftime("%a, %Y-%m-%d %H:%M:%S")) )
            #print("End MAM")
        except sleekxmpp.exceptions.IqTimeout:
            print("/// Timeout while reading history!!")
            print("--> Trying to reconnect..")
            self.reconnect()
            
            

    def __handle_mam_result_verbose(self, response):
        print("--> {}".format("complete." if response["mam_answer"]["complete"] else "incomplete"))

        result = response['mam_answer']['results']

        if len(result) == 0:
            print("No new messages.")
            #print( "==== {} ====".format(time.strftime("%a, %Y-%m-%d %H:%M:%S")) )
        else:
            self.__handle_mam_result(response)
            
        
        
    def __handle_mam_result(self, response):
        id_tmp = response["mam_answer"]["rsm"]["last"]
        if id_tmp:
            self.id_of_last_message = id_tmp
            self._config.set_last_message(self.id_of_last_message)
        
        result = response['mam_answer']['results']
            
        for x in result:
            msg = x["mam_result"]["forwarded"]["message"]
            delay = x["mam_result"]["forwarded"]["delay"]
            if msg["body"] or msg.xml.find('{eu.siacs.conversations.axolotl}encrypted'):
                print("--------")
                print("Time:", delay["stamp"].astimezone(tz=None).strftime("%a, %Y-%m-%d %H:%M:%S"))
                print("From:", msg["from"])
                print("To:  ", msg["to"])
                #print(msg)  ## XXX
                print()

        #if len(result) > 0:
            #print( "==== {} ====".format(time.strftime("%a, %Y-%m-%d %H:%M:%S")) )


    def message(self, msg):
        """
        Process incoming message stanzas. Be aware that this also
        includes MUC messages and error messages. It is usually
        a good idea to check the messages's type before processing
        or sending replies.

        Arguments:
            msg -- The received message stanza. See the documentation
                   for stanza objects and the Message stanza to see
                   how it may be used.
        """
        
        #print("Something happened oO: {}".format(msg['type']))
        
        
        ## TESTING
        print("/// Incoming message, type: " + msg['type'])
        
        if msg['type'] in ('chat', 'normal'):
            #print("/// New message arrived, checking history:")
            self.get_history(quiet=True)


if __name__ == '__main__':
    # Setup the command line arguments.
    optp = OptionParser()

    # Output verbosity options.
    optp.add_option('-q', '--quiet', help='set logging to ERROR',
                    action='store_const', dest='loglevel',
                    const=logging.ERROR, default=logging.INFO)
    optp.add_option('-d', '--debug', help='set logging to DEBUG',
                    action='store_const', dest='loglevel',
                    const=logging.DEBUG, default=logging.INFO)
    optp.add_option('-v', '--verbose', help='set logging to COMM',
                    action='store_const', dest='loglevel',
                    const=5, default=logging.INFO)

    # JID and password options.
    #optp.add_option("-j", "--jid", dest="jid",
                    #help="JID to use")
    #optp.add_option("-p", "--password", dest="password",
                    #help="password to use")

    opts, args = optp.parse_args()

    # Setup logging.
    logging.basicConfig(level=opts.loglevel,
                        format='%(levelname)-8s %(message)s')


    ## Load config
    config = Config( os.path.expanduser("~/.config/xmpp-history-alert") )
    
    # Setup the Client and register plugins. Note that while plugins may
    # have interdependencies, the order in which you register them does
    # not matter.
    xmpp = HistoryAlert(config.get_jid(), config.get_password(), config)
    xmpp.register_plugin('xep_0199')  # XMPP Ping
    xmpp.register_plugin("xep_0313")  # MAM
    xmpp.register_plugin("xep_0004")  # Data Form (required by xep_0313)

    # Connect to the XMPP server and start processing XMPP stanzas.
    if xmpp.connect():
        # If you do not have the dnspython library installed, you will need
        # to manually specify the name of the server if it does not match
        # the one in the JID. For example, to use Google Talk you would
        # need to use:
        #
        # if xmpp.connect(('talk.google.com', 5222)):
        #     ...
        xmpp.process(block=True)
        print("Done")
    else:
        print("Unable to connect.")
