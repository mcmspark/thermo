#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ai ts=4 sts=4 et sw=4 nu
import kivy
kivy.require('1.8.0')
import sys
import traceback
import serial
import urllib
import re
import subprocess
import json
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTClient
from AWSIoTPythonSDK.MQTTLib import AWSIoTMQTTShadowClient

from Adafruit_BME280 import *

from collections import deque
from kivy.app import App
from kivy.base import runTouchApp
from kivy.clock import Clock
from kivy.config import Config
from kivy.core.window import Window

from kivy.graphics import Color, Rectangle
from kivy.properties import ObjectProperty
from kivy.properties import StringProperty
from kivy.properties import ListProperty
from kivy.uix.button import Button
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.vkeyboard import VKeyboard
from kivy.utils import get_color_from_hex as rgb
from time import time, sleep, gmtime, strftime, localtime
import datetime
# CONSTANTS
DATE_FORMAT='%Y%m%d %H:%M:%S'

def tformat(temp):
	return "{:2.1f}".format(float(temp)*9/5+32.0)

# pitft uses SPI pins (SCK, MOSI, MISO, CE0, CE1) 7,8,9,10,11 plus 24 and 25. 
# GPIO 18 is used to PWM dim the backlight
# I2C is ues for the BME280 GPIO 2 and 3
# UART is used for the Sensor network GPIO 14 and 15
# GPIO  17, 27, and 22 are used for driving zones expandable to 23 and 4
subprocess.call(["gpio", "-g", "mode", "17", "out"])
subprocess.call(["gpio", "-g", "write", "17", "0"])

subprocess.call(["gpio", "-g", "mode", "27", "out"])
subprocess.call(["gpio", "-g", "write", "27", "0"])

subprocess.call(["gpio", "-g", "mode", "22", "out"])
subprocess.call(["gpio", "-g", "write", "22", "0"])

subprocess.call(["gpio", "-g", "mode", "18", "pwm"])
subprocess.call(["gpio", "pwmc", "600"])
subprocess.call(["gpio", "-g", "pwm", "18", "256"])

class ShadowLabel(Label):
	decal = ListProperty([0, 0])
	tint = ListProperty([1, 1, 1, 1])

class ThermoWidget(FloatLayout):
	currentBrightness=100
	weatherText=StringProperty()
	picSource=StringProperty()
	tempDataText=StringProperty()
	setPointText=StringProperty()
	ipAddressText=StringProperty()
	averageTempText=StringProperty()
	zoneAlertsText=StringProperty()
	
	def brighter(self):
		self.currentBrightness=100 if self.currentBrightness == 1023 else 1023
		self.setDisplayBrightness(str(self.currentBrightness))
		return

	def reboot(self):
		subprocess.call(["reboot"])
		return

	def setDisplayBrightness(self, percent):
		subprocess.call(["gpio", "-g", "pwm", "18", percent])
		return
class ThermoDevice():
	def __init__(self,id,zone,location,temp=0.0,lastupdate='',desc=None,batt=None,press=None,humid=None):
		self.id=id
		self.temp=temp
		self.zone=zone
		self.location=location
		self.lastupdate=lastupdate
		self.desc=desc
		self.batt=batt
		self.press=press
		self.humid=humid
		self.alert=''

class Furnace():
	def __init__(self,onSeconds=0.0,offSeconds=0.0,maxBurnSeconds=0.0,maxRestSeconds=0.0,status=False):
		self.onSeconds=onSeconds
		self.offSeconds=offSeconds
		self.maxBurnSeconds=maxBurnSeconds
		self.maxRestSeconds=maxRestSeconds
		self.status=status
		self.lastupdate=''

class ThermoZone():
	def __init__(self,id,port,temp=0.0,lastupdate='',alert=''):
		self.id=id
		self.port=port
		self.triggertemp=temp
		self.lastupdate=lastupdate
		self.alert=''
		self.status=False
		self.setPoint=20.0
		self.average=20.0
		
class ThermoApp(App):
	DEVICE = '/dev/ttyAMA0'
	BAUD = 9600
	TIMEOUT = 5
	ipaddr=''
	lastGPUTempRead=0.0
	lastWeatherRead=0.0
	lastTempPressHumidRead=0.0
	lastShadowUpdate=0.0
	lastSetAlerts=0.0
	ui = ObjectProperty(None)
	zones = ObjectProperty(None)
	zonemap=['','17','27','22']
	zoneData={
		'1':ThermoZone(1,17),
		'2':ThermoZone(2,27),
		'3':ThermoZone(3,22)
	}
	furnace=Furnace()
	currentZone=1
	dataFeed = deque()
	
	deviceData={
		'AA':ThermoDevice('AA',2,'master'),
		'AB':ThermoDevice('AB',2,'tess'),
		'AC':ThermoDevice('AC',2,'kate'),
		'AD':ThermoDevice('AD',3,'girls'),
		'AE':ThermoDevice('AE',1,'snug'),
		'AF':ThermoDevice('AF',1,'living'),
		'AG':ThermoDevice('AG',0,'porch'),
		'AH':ThermoDevice('AH',1,'ground'),
		'BM':ThermoDevice('BM',0,'thermo'),
		'AW':ThermoDevice('AW',0,'weather'),
		'PI':ThermoDevice('PI',0,'GPU')}
	ser = serial.Serial(DEVICE, BAUD)
	
	voltage = 0.0
	tempvale = 0.0
	pressure = 0.0
	weather = []
	sensor = BME280(mode=BME280_OSAMPLE_8)
	host='a2pveb84akyryv.iot.us-east-1.amazonaws.com'
	rootCAPath='rootca.key'
	privateKeyPath='bdca28f300.private.key'
	certificatePath='bdca28f300.cert.pem'
	# -e a2pveb84akyryv.iot.us-east-1.amazonaws.com -r rootca.key -c bdca28f300.cert.pem -k bdca28f300.private.key

	def show_config(self):
		App.open_settings(self)
		Window.request_keyboard(self.keyboard_close, self)
	
	def keyboard_close(self):
		#print "close"
		return

	def build_config(self, config):
		config.setdefaults('startup', {
	    		'weatherText': 'foobar',
	    		'picSource': 'weather/1.jpg'
		})
		self.config=config

	def build_settings(self, settings):
		jsondata = """[
			{ "type": "title",
			"title": "Thermo application" },
			{ "type": "options",
			"title": "Initial Weather",
			"desc": "Weather Pic",
			"section": "startup",
			"key": "picSource",
			"options": ["weather/1.jpg", "weather/images.jpg", "weather/part_coudy.jpg"] },
			{ "type": "string",
			"title": "Weather Title",
			"desc": "Weather Text",
			"section": "startup",
			"key": "weatherText" }]"""
		settings.add_json_panel('Thermo application', self.config, data=jsondata)

	def build(self):
		self.ui=ThermoWidget()
		self.ui.weatherText='ThermoWidget'
		self.ui.picSource='weather/1.jpg'
		self.ui.tempDataText="temps"
		self.ui.setPointText="0.0"
		self.ui.ipAddressText="192.168.0.0"
		self.ui.averageTempText="0.0"
		self.ui.zoneAlertsText="Loading..."
		btn=self.ui.ids['increase']
		btn.bind(on_release=self.increaseSetPoint)
		btn=self.ui.ids['decrease']
		btn.bind(on_release=self.decreaseSetPoint)
		self.zones=self.ui.ids['zones']
		for z in range(0,4):
			btnstate='down' if self.currentZone==z else 'normal'
			btn = ToggleButton(
				allow_no_selection=False,
				text=str(z), 
				group='zonegroup', 
				size_hint=(None, None),
				halign='center',
				state=btnstate,
				background_normal='normal.png',
				background_down='down.png')
    			btn.bind(on_release=self.switch_zone)
    			self.zones.add_widget(btn)
		self.ui.weatherText=self.config.get('startup', 'weatherText')
		temp = subprocess.check_output(["ifconfig","wlan0"],universal_newlines=True)
		pos1=temp.find("inet addr:")
		pos2=temp.find(" Bcast:")
		self.ui.ipAddressText=temp[pos1+10:pos2]
		self.connectMQTT()
		Clock.schedule_interval(self.mainLoop, 10.0)
		return self.ui

	def switch_zone(self,toggle):
		self.currentZone=int(toggle.text)
		self.updateDisplay()
		pass

	def increaseSetPoint(self,instance):
		self.zoneData[str(self.currentZone)].setPoint+=5.0/9.0
		self.takeAction()
		self.updateDisplay()
		pass

	def decreaseSetPoint(self,instance):
		self.zoneData[str(self.currentZone)].setPoint-=5.0/9.0
		self.takeAction()
		self.updateDisplay()
		pass

	def loadConfig(self):
		# read config file into memory vars
		return

	def avgZone(self,zonenum):
		tot=0.0
		cnt=0
		for i in self.deviceData:
			device=self.deviceData[i]
			if(device.zone==zonenum):
				tot+=float(device.temp)
				if(device.temp>0.0):
					cnt+=1
		if cnt==0:
			cnt=1
		return tot/cnt
	
	def connectMQTT(self):
		self.myShadowClient = AWSIoTMQTTShadowClient("thermo")
    		#self.myAWSIoTMQTTClient = AWSIoTMQTTClient("thermo")

		self.myShadowClient.configureEndpoint(self.host, 8883)
		self.myShadowClient.configureCredentials(self.rootCAPath, self.privateKeyPath, self.certificatePath)

		# myShadowClient connection configuration
		self.myShadowClient.configureAutoReconnectBackoffTime(1, 32, 20)
		
		self.myShadowClient.connect()

		self.myAWSIoTMQTTClient = self.myShadowClient.getMQTTConnection()
		self.myAWSIoTMQTTClient.configureOfflinePublishQueueing(-1)  # Infinite offline Publish queueing
		self.myAWSIoTMQTTClient.configureDrainingFrequency(2)  # Draining: 2 Hz
		self.myAWSIoTMQTTClient.configureConnectDisconnectTimeout(10)  # 10 sec
		self.myAWSIoTMQTTClient.configureMQTTOperationTimeout(5)  # 5 sec
		

		# Connect and subscribe to AWS IoT
		#self.myAWSIoTMQTTClient.connect()
		# myAWSIoTMQTTClient.subscribe("thermo", 1, customCallback)
		# self.myAWSIoTMQTTClient.publish("thermo", "[[\'"+(strftime(DATE_FORMAT,localtime())+"\','TT','START','1']]", 1)
		# Create a device shadow instance using persistent subscription
		self.myDeviceShadow = self.myShadowClient.createShadowHandlerWithName("mythermo", True)
		return

	def updateDeviceShadow(self):
		if(time()-self.lastShadowUpdate > 300):
			thingState={
				"state" : {
					"reported" : {
						"sensors" : {
						},
						"zones" : {
						},
						"furnace" : {
						}
					}
				}
			}
			for i in self.deviceData:
				device=self.deviceData[i]
				thingState["state"]["reported"]["sensors"][device.id]={"temp":tformat(device.temp),"location":device.location,"batt":device.batt,"alert":device.alert,"lastupdate":device.lastupdate,"press":device.press,"humid":device.humid}
			for i in self.zoneData:
    				zone=self.zoneData[i]
				thingState["state"]["reported"]["zones"][zone.id]={"status":zone.status, "average":tformat(zone.average), "setPoint":tformat(zone.setPoint), "triggertemp":tformat(zone.triggertemp), "alert":zone.alert}
			thingState["state"]["reported"]["furnace"]={"onSeconds":self.furnace.onSeconds,"offSeconds":self.furnace.offSeconds,"maxBurnSeconds":self.furnace.maxBurnSeconds,"maxRestSeconds":self.furnace.maxRestSeconds,"status":self.furnace.status,"lastupdate":self.furnace.lastupdate}
			self.myDeviceShadow.shadowUpdate(json.dumps(thingState), None, 5)
			self.lastShadowUpdate=time()
		return	
		
	def updateDisplay(self):
		# draw everything
		# if click then show subpanel or change config
		self.ui.setPointText="{:2.0f}".format(self.zoneData[str(self.currentZone)].setPoint*9/5+32.0)
		self.ui.averageTempText=tformat(self.avgZone(self.currentZone))
		self.ui.tempDataText=''
		zonealerts='Alerts:'
		for i in self.deviceData:
			device=self.deviceData[i]
			thisDeviceText=tformat(device.temp)
			thisDeviceText+=" "+device.location+" "+device.alert
			self.ui.tempDataText+=thisDeviceText+'\n'
		for i in self.zoneData:
    			zone=self.zoneData[i]
			if(len(zone.alert)>0):
				zonealerts+=" Zone"+str(zone.id)+" "+zone.alert
		self.ui.zoneAlertsText=zonealerts
		return
	
	def readSensors(self):
		# get data from serial RF sensors
		# get data from remote PI
		# all data in memory only in this function
		# get temperature
		# messages are 12chars aIDTYPEVALUE aIDAWAKE---- or aIDSLEEPING-
		# returns -100 on error, or the temperature as a float
		
		fim = time()+ self.TIMEOUT
		
		voltage = 0
		tempvalue = -100
		deviceid = ''
		while (time()<fim) and (tempvalue == -100):
			n = self.ser.inWaiting()
			if n != 0:
				data = self.ser.read(n)
				nb_msg = len(data) / 12
				for i in range (0, nb_msg):
					msg = data[i*12:(i+1)*12]
		
					deviceid = msg[1:3]
					if self.deviceData.has_key(deviceid):
						device=self.deviceData[deviceid]
						device.lastupdate=strftime(DATE_FORMAT,localtime())
			
						if msg[3:7] == "TEMP":
							tempvalue = msg[7:]
							device.temp=tempvalue
							self.dataFeed.append((strftime(DATE_FORMAT,localtime()), deviceid, "TEMP", tempvalue))

						if msg[3:7] == "BATT":
							voltage = msg[7:11]
							if voltage == "LOW":
								voltage = 0.1
							device.batt=voltage
							self.dataFeed.append((strftime(DATE_FORMAT,localtime()), deviceid+'B', "BATT", voltage))

			else:
				sleep(5)
		return

	def getPiSensorData(self):
		if(time()-self.lastGPUTempRead > 60):
			temp = ""
			temp = subprocess.check_output(["/opt/vc/bin/vcgencmd","measure_temp"],universal_newlines=True)
			temp = temp[5 : -3]
			device=self.deviceData['PI']
			device.lastupdate=strftime(DATE_FORMAT,localtime())
			device.temp=temp
			self.dataFeed.append((strftime(DATE_FORMAT,localtime()), "PI", "TEMP", temp))
			self.lastGPUTempRead = time()
		return

	def getConnectedSensorData(self):
		if(time()-self.lastTempPressHumidRead > 60):
			# get BME280 data
			temp=self.sensor.read_temperature()-1.0
			press=self.sensor.read_pressure()
			humid=self.sensor.read_humidity()
			self.pressure=press
			device=self.deviceData['BM']
			device.lastupdate=strftime(DATE_FORMAT,localtime())
			device.temp=temp
			device.press=press
			device.humid=humid
			self.dataFeed.append((strftime(DATE_FORMAT,localtime()), "BM", "TEMP", temp))
			self.dataFeed.append((strftime(DATE_FORMAT,localtime()), "BP", "PRESS", press))
			self.dataFeed.append((strftime(DATE_FORMAT,localtime()), "BH", "HUMID", humid))
			self.lastTempPressHumidRead = time()

	def getWeather(self):
		if(time()-self.lastWeatherRead > 1800):
			# get and parse AccuWeather data
			cur = re.compile('Currently: (.*)<')
			link = "http://rss.accuweather.com/rss/liveweather_rss.asp?metric=0&locCode=US|44022"
			f = urllib.urlopen(link)
			myfile = f.read()
			tempvalue = cur.search(myfile).group(1)
			temp=tempvalue[-4:-1]
			pos=tempvalue.find(":")
			description=tempvalue[0:-5] if pos<0 else tempvalue[0:pos]
			description=description.replace(" ","_").lower()
			# print("description = [" + description +"]")
			device=self.deviceData['AW']
			device.lastupdate=strftime(DATE_FORMAT,localtime())
			device.temp=(float(temp)-32)*5/9
			if device.desc<>description :
				self.ui.picSource='weather/'+description+'.jpg' if 6 < localtime()[3] < 18 else 'weather/'+description+'_dark.jpg'
			device.desc=description
			self.ui.weatherText = tempvalue
			self.dataFeed.append((strftime(DATE_FORMAT,localtime()), "AW", "NEWS", tempvalue))
						
			self.lastWeatherRead = time()
		return
	def setAlerts(self):
		# Reasons for alerts:
		# sensor battery level below 2.3
		# sensor not reporting ( sensor data age > 5x reporting )
		# temperature not under control = falling when attempting to raise
		#    alert if temp not correct direction for 10 minutes
		#    need control switch date time 
		if(time()-self.lastSetAlerts > 1800):
			for i in self.deviceData:
    				device=self.deviceData[i]
				device.alert=""
				if (not device.batt is None) & (device.batt<2.5):
    					device.alert="LOW"
					self.dataFeed.append((strftime(DATE_FORMAT,localtime()), "ALERT", "LOW Battery in "+device.location, device.batt))
					self.lastSetAlerts = time()
				if (len(device.lastupdate)>0) & (device.id!='AW'): 
					age = datetime.datetime.strptime(strftime(DATE_FORMAT,localtime()),DATE_FORMAT) - datetime.datetime.strptime(device.lastupdate,DATE_FORMAT)
					#print "{} {}".format(device.location,age.seconds)
					if ( age.seconds > 600 ):
						device.alert="OLD"
						self.dataFeed.append((strftime(DATE_FORMAT,localtime()), "ALERT", "NO Response in "+device.location, age.seconds))
						self.lastSetAlerts = time()
			for i in self.zoneData:
    				zone=self.zoneData[i]
				zone.alert=""
				if (zone.status):
					age = datetime.datetime.strptime(strftime(DATE_FORMAT,localtime()),DATE_FORMAT) - datetime.datetime.strptime(zone.lastupdate,DATE_FORMAT)
					if (age.seconds>600):
						zone.alert="OOC"
						self.dataFeed.append((strftime(DATE_FORMAT,localtime()), "ALERT", "OOC in zone "+str(zone.id), tformat(zone.average)))
						self.lastSetAlerts = time()
		return

	def uploadData(self):
		# put the data in the cloud or cache in a file until sucess
		# add it to the memory deque
		# if the deque > 10 try to upload it and any pending updates
		# else throw a flag for pending updates and write to a file
		if len(self.dataFeed)>10:
    			try:
				# write to a file
				#print "  write to file"
				with open("Output.txt", "a") as text_file:
					for record in self.dataFeed:
						text_file.write("{},{},{},{}\r\n".format(record[0],record[1],record[2],record[3]))
				# write to cloud
				#print "  write to cloud"

				self.myAWSIoTMQTTClient.publish("thermo", json.dumps(list(self.dataFeed)), 1)
				# clear the deque
				self.dataFeed.clear()
			except:
				print("Unexpected error in uploadData:", sys.exc_info()[0])
		return
		
	def downloadRequests(self):
		# get cloud data or web requests
		return
		
	def controlZone(self,zone,on,avg):
		zoneentry=self.zoneData[str(zone)]
		subprocess.call(["gpio", "-g", "write", str(zoneentry.port), "1" if on else "0"])
    		furnaceWasOn=False
		for i in self.zoneData:
			furnaceWasOn|=self.zoneData[i].status
		if(zoneentry.status != on):
			zoneentry.status=on
			furnaceIsOn=False
			for i in self.zoneData:
				furnaceIsOn|=self.zoneData[i].status
			if(furnaceIsOn!=furnaceWasOn):
				self.furnace.status=furnaceIsOn
				if (len(self.furnace.lastupdate)>0):
					age = datetime.datetime.strptime(strftime(DATE_FORMAT,localtime()),DATE_FORMAT) - datetime.datetime.strptime(self.furnace.lastupdate,DATE_FORMAT)
					# if it is now on  - age is how long it was off
					if(furnaceIsOn):
						self.furnace.offSeconds+=age.seconds
						if(age.seconds>self.furnace.maxRestSeconds):
							self.furnace.maxRestSeconds=age.seconds
					# if it is now off - age is how long it was on
					else:
						self.furnace.onSeconds+=age.seconds
						if(age.seconds>self.furnace.maxBurnSeconds):
							self.furnace.maxBurnSeconds=age.seconds
				self.furnace.lastupdate=strftime(DATE_FORMAT,localtime())
			zoneentry.lastupdate=strftime(DATE_FORMAT,localtime())
			zoneentry.triggertemp=avg
		return

	def takeAction(self):
		# contains all rules to make decisions based on data 
		for i in self.zoneData:
			zone=self.zoneData[i]
			zone.average=self.avgZone(zone.id)
			if(zone.average<10.0):
				self.controlZone(zone.id,False,zone.average)
				return
			#print "average in zone {} is {}".format(zone.id,zone.average)
    			if(zone.average<zone.setPoint-0.5):
    				self.controlZone(zone.id,True,zone.average)
    				#turn it on
			if(zone.average>zone.setPoint):
				self.controlZone(zone.id,False,zone.average)
    				#turn it off
		return
	
	def mainLoop(self,args):
		try:
			#print 'config'
			self.loadConfig()
			#print 'getWeather'
			self.getWeather()
			#print 'getPI'
			self.getPiSensorData()
			#print 'getBME'
			self.getConnectedSensorData()
			#print 'read'
			self.readSensors()
			#print 'alerts'
			self.setAlerts()
			#print 'update'
			self.updateDisplay()
			#print 'update shadow'
			self.updateDeviceShadow()
			#print 'upload'
			self.uploadData()
			#print 'download'
			self.downloadRequests()
			#print 'action'
			self.takeAction()
		except:
			type_, value_, traceback_ = sys.exc_info()
			print "EXCEPTION {}\r\n{}\r\n{}".format(type_, value_, traceback.format_tb(traceback_))
			self.dataFeed.append(value_)
		return
	
if __name__ == '__main__':
    ThermoApp().run()	


