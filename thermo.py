#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim: ai ts=4 sts=4 et sw=4 nu
import kivy
from kivy.app import App
from kivy.utils import get_color_from_hex as rgb
from kivy.clock import Clock
from kivy.uix.image import Image
from kivy.graphics import Color, Rectangle
from kivy.uix.label import Label
import serial
from time import time, sleep, gmtime, strftime, localtime
import urllib
import re

class Thermo(App):
	DEVICE = '/dev/ttyAMA0'
	BAUD = 9600
	TIMEOUT = 5
	lastWeatherRead=0.0
	updated=False
	locs = ['master','tess','hall','lr','window']
	devices = ['AA','AB','AC','AD','AE','AW']
	temps = [0.0,0.0,0.0,0.0,0.0,0.0]
	batts = [0.0,0.0,0.0,0.0,0.0,0.0]
	times = [0.0,0.0,0.0,0.0,0.0,0.0]
	ser = serial.Serial(DEVICE, BAUD)
	voltage = 0.0
	tempvale = 0.0
	setpt = []
	def build(self):	
		picture=Image(source='weather/download.jpg', allow_stretch=True)				
		self.setpt = Label(font_size=44, markup=True, text="hello", pos=(55,55))
		with picture.canvas:
			Color(1,0,0,0.5)
			Rectangle(pos=(50, 75), size=(270,175))

		picture.add_widget(self.setpt)
		Clock.schedule_interval(self.mainLoop, 10.0)
		return picture

	def loadConfig(self):
		# read config file into memory vars
		return
	
	def updateDisplay(self):
		# draw everything
		# if click then show subpanel or change config
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
					if not( deviceid in self.devices ):
						self.devices.append(deviceid)
		
					if msg[3:7] == "TEMP":
						tempvalue = msg[7:]
						self.temps[self.devices.index(deviceid)]=tempvalue
						self.updated=True

					if msg[3:7] == "BATT":
						voltage = msg[7:11]
						if voltage == "LOW":
							voltage = 0
						self.batts[self.devices.index(deviceid)]=voltage
			else:
				sleep(5)
		return

	def getWeather(self):
		if(time()-self.lastWeatherRead > 1800):
			# get and parse AccuWeather data
			cur = re.compile('Currently: (.*)<')
			link = "http://rss.accuweather.com/rss/liveweather_rss.asp?metric=0&locCode=US|44022"
			f = urllib.urlopen(link)
			myfile = f.read()
			tempvalue = cur.search(myfile).group(1)

			self.temps[self.devices.index('AW')]=tempvalue
			self.updated=True		
			self.setpt.text = tempvalue
			self.lastWeatherRead = time()
		return
	
	def uploadData(self):
		# put the data in the cloud or cache in a file until sucess
		# add it to the memory deque
		# if the deque > 10 try to upload it and any pending updates
		# else throw a flag for pending updates and write to a file
		if self.updated:
			self.updated=False
			with open("Output.txt", "a") as text_file:
				text_file.write("{},{},{}\r\n".format(strftime('%a, %d %b %Y %H:%M:%S',localtime()),self.temps, self.batts))
		return
		
	def downloadRequests(self):
		# get cloud data or web requests
		return
		
	def takeAction(self):
		# contains all rules to make decisions based on data 
		return
	
	def mainLoop(self,args):
		self.loadConfig()
		self.getWeather()
		self.readSensors()
		self.updateDisplay()
		self.uploadData()
		self.downloadRequests()
		self.takeAction()
	
if __name__ == '__main__':
	Thermo().run()


