import os
import os.path
import sqlite3
import urllib
import urllib2
import time
import json
import socket
import sys
import datetime
import base64
import markdown
import threading

from json import load
from urllib2 import urlopen

import cherrypy
from cherrypy.process.plugins import Monitor

# below are helper .py files
import encrypt
import db_calls
import time_formatting


DB_STRING = "users.db"
reload(sys)
sys.setdefaultencoding('utf8')
listen_ip = '172.23.68.189'# socket.gethostbyname(socket.getfqdn())
listen_port = 10002
api_calls = 0

def resetTimer():  # resets the api_calls counter every minute
    print("API Calls timer reset")
    global api_calls
    api_calls = 0

t = Monitor(cherrypy.engine, resetTimer, frequency=60).start()  # start threading function, 30 seconds

def LimitReached():  # this function will return True if limit reached/user has been blacklisted
    # firstly check if IP address has been blacklisted
    ip = cherrypy.request.headers["Remote-Addr"]  # this info from header has caller IP information
    c = sqlite3.connect(DB_STRING)
    cur = c.cursor()
    cur.execute("SELECT ip FROM blacklist")
    blacklist = cur.fetchone()  # blackListing/rate-limiting has similar use cases, might as well
    if blacklist:  # if users were found on the blacklist
        for i in range(0, len(blacklist)):  # search through the list
            if ip == blacklist[i]:  # a match was found with the calling ip and somebody in the blacklist
                print("A blacklisted user tried to call your functions")
                return True
    global api_calls
    api_calls = api_calls + 1
    print('Current calls:' + str(api_calls))
    if (api_calls > 14):  # if 15 people have called my functions within 60 seconds
        print("Rate limit activated, a user was blocked from your API")
        return True  #  block the request and return Error 11: Blacklisted or Rate Limited (done in other funcs)
    else:
        return False # let the user have the information

class MainApp(object):
    logged_on = 0  # 0 = never tried to log on, 1 = success, 2 = tried and failed, 3 = success and logged out

# The functions below are served directly as HTML. Replace has been called to add in important python-based output.

    @cherrypy.expose
    def index(self):
        f = open("index.html", "r")
        data = f.read()
        f.close()
        # need conditional to show error message if login failed
        if (self.logged_on == 2):  # 2 shows up if a failed login attempt has been made
            data = data.replace("LOGIN_STATUS", "Login attempt failed. Please try again.")
        elif (self.logged_on == 3):
            data = data.replace("LOGIN_STATUS", "Logged out successfully. Thanks for using fort secure chat.")
        else:  # if no login attempt has been made or login successful, do not show prompt
            data = data.replace("LOGIN_STATUS", "")
        return data

    @cherrypy.expose
    def home(self):
        f = open("home.html", "r")
        data = f.read()
        f.close()
        try:
            data = data.replace("USER_NAME", cherrypy.session.get('username'))
        except:
            return "You are not logged in. Click " + "<a href='/'>here</a> to login"  # in case the session had timed out
        data = data.replace("USERS_ONLINE", self.getList())
        data = data.replace("LIST_OF_TOTAL_USERS", self.listAllUsers())
        data = data.replace("PLACEHOLDER", self.getChatConvo())
        return data

    @cherrypy.expose
    def files(self):
        f = open("files.html", "r")
        data = f.read()
        f.close()
        try:
            data = data.replace("USER_NAME", cherrypy.session.get('username'))
        except:
            return "You are not logged in. Click " + "<a href='/'>here</a> to login"
        data = data.replace("USER_FILES", self.displayFile())
        data = data.replace("USERS_ONLINE", self.getList())
        return data

    @cherrypy.expose
    def viewProfiles(self):
        f = open("viewProfiles.html", "r")
        data = f.read()
        f.close()
        try:
            data = data.replace("USER_NAME", cherrypy.session.get('username'))
        except:
            return "You are not logged in. Click " + "<a href='/'>here</a> to login"
        data = data.replace("LIST_OF_TOTAL_USERS", self.listAllUsers())
        data = data.replace("PLACEHOLDER", self.displayProfile())
        return data

    @cherrypy.expose
    def logs(self):
        f = open("logs.html", "r")
        data = f.read()
        try:
            data = data.replace("USER_NAME", cherrypy.session.get('username'))
        except:
            return "You are not logged in. Click " + "<a href='/'>here</a> to login"
        f.close()
        return data

    secret = ''
    @cherrypy.expose
    def twoFA(self):  # only for first time logins, QR code displayed
        f = open("twoFA.html", "r")
        data = f.read()
        f.close()
        self.secret = encrypt.generateBase32(cherrypy.session.get('username'))
        print("SECRET GENERATED:")
        print(self.secret)
        data = data.replace("QR_CODE", self.generateQR(self.secret))
        return data

    @cherrypy.expose
    def twoFAcode(self):
        f = open("twoFAcode.html", "r")
        data = f.read()
        f.close()
        return data

    @cherrypy.expose
    def validate2FA(self, code):
        # edge case if MSB of code is 0, getTotpToken would return a 5 digit number
        if code[0] == '0':
            code = code[1:]  # new client-input code to validate doesnt include MSB

        # first check if the user has logged in before, i.e. users in user_credentials table.
        # check against the secret generated upon the very first user login.
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT username FROM user_credentials WHERE username=?", [cherrypy.session.get('username')])
        credentials = cur.fetchone()
        if credentials:  # the user has indeed logged in before
            cur2 = c.cursor()
            cur2.execute("SELECT secret FROM user_credentials WHERE username=?", [cherrypy.session.get('username')])
            results = cur2.fetchone()  # secret is the same one from before
            self.secret = results[0]  # override generated secret with old one
            print ("Previously logged in user detected!")

        print(int(code))
        print(encrypt.getTotpToken(self.secret))
        if (int(code) == encrypt.getTotpToken(self.secret)):
            print("twoFA successfully authenticated")
            with sqlite3.connect(DB_STRING) as c:  # table also in re-calling /report in another thread
                c.execute("INSERT INTO user_credentials(username, password, location, ip, port, secret) VALUES (?,?,?,?,?,?)",
                [cherrypy.session.get('username'), cherrypy.session.get('password'), cherrypy.session.get('location'),
                cherrypy.session.get('ip'),cherrypy.session.get('port'), self.secret])
            raise cherrypy.HTTPRedirect('/home')
        else:
            self.logged_on = 2
            cherrypy.lib.sessions.expire()
            raise cherrypy.HTTPRedirect('/')


    def generateQR(self, secret):
        # this function generates a QR code based on the secret. Google Auth also displays the current logged in user's details
        # https://www.google.com/chart?chs=200x200&chld=M|0&cht=qr&chl=otpauth://totp/Example%3Aalice%40google.com%3Fsecret%3DJBSWY3DPEHPK3PXP%26issuer%3DExample
        params = {"secret": secret, "issuer": 'fortsecurechat'}
        urllib.urlencode(params)
        return '<img height="250" width="250" src="' + 'https://chart.googleapis.com/chart?chs=250x250&chld=M|0&cht=qr&chl=' + \
               'otpauth%3A%2F%2Ftotp%2F' + str(cherrypy.session.get('username')) + '%3Fsecret%3D' + str(secret) + '%26issuer%3Dfort%2Dsecure%2Dchat" />'

    @cherrypy.expose
    def report(self, username, password, location='1', ip='202.36.244.10', port=listen_port):  # TODO: change ip = back to listen_ip
        hashedPassword = encrypt.hash(password)  # call hash function for SHA256 encryption
        auth = self.authoriseUserLogin(username, hashedPassword, location, ip, port)
        error_code,error_message = auth.split(",")
        if (error_code == '0'):  # successful login, populate session variables
            self.logged_on = 1
            cherrypy.session['username'] = username
            cherrypy.session['password'] = hashedPassword
            cherrypy.session['location'] = location
            cherrypy.session['ip'] = ip
            cherrypy.session['port'] = port
            t = Monitor(cherrypy.engine, MainApp().reportThreaded, frequency=30).start()  # start threading function, 30 seconds
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT username FROM user_credentials WHERE username=?", [username])
            credentials = cur.fetchone()
            if not credentials:  # couldn't find, thus user has never logged on before and needs 2FA QR
                #store username and password in user_credentials table; logoffForced (on application exit/crash), threaded /report and 2FA uses this
                raise cherrypy.HTTPRedirect('/twoFA')
            else:  # a returning user is back, so go to /twoFAcode to get them just to enter their TOTP again
                raise cherrypy.HTTPRedirect('/twoFAcode')
        else:
            print("ERROR: " + error_code)
            self.logged_on = 2
            raise cherrypy.HTTPRedirect('/')  # set flag to change /index function

    def reportThreaded(self):  # take user credentials data and /report with that
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT username, password, location, ip, port FROM user_credentials")
        credentials = cur.fetchone()
        auth = self.authoriseUserLogin(credentials[0],credentials[1],credentials[2],credentials[3],credentials[4])
        print("/report called!")
        return auth

    def authoriseUserLogin(self,username, password, location, ip, port):
        params = {'username':username, 'password':password, 'location':location, 'ip':ip, 'port':port}
        full_url = 'http://cs302.pythonanywhere.com/report?' + urllib.urlencode(params)  # converts to format &a=b&c=d...
        return urllib2.urlopen(full_url).read()

    @cherrypy.expose
    def blackList(self, choice, username):  # this function is called if the blacklist form on home.html is called
        if choice == 'Block':  # if user chose Block from dropdown on home.html
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT ip FROM user_string WHERE username=?", [username])
            creds = cur.fetchone()
            if not creds:  # couldn't find username's IP address in user string
                return 'IP not found, user may not be online. Click ' + '<a href="/home">here</a> to go back.'
            else:
                with sqlite3.connect(DB_STRING) as c:  # insert the name into blacklist
                    c.execute("INSERT INTO blacklist(username, ip) VALUES (?,?)",
                    [username,creds[0]])
        else: # Unblock was chosen
            with sqlite3.connect(DB_STRING) as c:
                c.execute("DELETE FROM blacklist WHERE username=?", [username])  # delete the name from blacklist
        raise cherrypy.HTTPRedirect('/home')  # refresh the page


    @cherrypy.expose
    def listAllUsers(self):
        url = 'http://cs302.pythonanywhere.com/listUsers'
        api_call = urllib2.urlopen(url).read()  # call login server API and store the result
        total_users_list = api_call.split(",")  # create a list by splitting based on comma, as based on string format of output
        total_users_string = ''
        for i in range(0, len(total_users_list)):
            if total_users_list[i] != cherrypy.session.get('username'):  # don't add the current user to list of possible msg-ers
                total_users_string += '<li class="person">' + \
                '<img src="' + db_calls.getProfilePic(total_users_list[i]) + '"/>' + '<span class="name">' + \
                str(total_users_list[i]) + '</span>' + \
                '<span class="preview">' + db_calls.checkOnline(total_users_list[i]) + '</span></li>'
        return total_users_string

    @cherrypy.expose
    @cherrypy.tools.json_in()
    def getStatus(self): # other people call this to get access to my status table
        if LimitReached():
            return 'Error 11: Blacklisted or Rate Limited'
        else:
            try:
                c = sqlite3.connect(DB_STRING)
                cur = c.cursor()
                cur.execute("SELECT status FROM user_status WHERE profile_username=?", [cherrypy.request.json['profile_username']])
                credentials = cur.fetchone()
                cred_dict = {"status": credentials[0]}
                print("Someone grabbed your profile status!")
                return json.dumps(cred_dict)  # return out a JSON encoded string
            except:  # apologise for not having the person the user wants
                print("You tried to serve a status to someone, but you don't have that status")
                return "Sorry, I don't have the status of the user you're looking for."

    @cherrypy.expose
    def setStatus(self, status):  # this function is called internally to set our own status, don't bother with JSON
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("""
        UPDATE user_status SET status=? WHERE profile_username=?""",
        (status, cherrypy.session.get('username')))
        c.commit()  # thank you stack overflow

    @cherrypy.expose
    def grabStatus(self, username):
        try:
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT ip, port FROM user_string WHERE username=?",[username])
            values = cur.fetchone()
            if not values:
                return '3: Client Currently Unavailable'
            else:
                ip = values[0]
                port = values[1]
                profile_dict = {"profile_username": username}
                params = json.dumps(profile_dict)

                try:
                    req = urllib2.Request("http://" + ip + ":" + port + "/getStatus",
                    params, {'Content-Type': 'application/json'})
                    response = urllib2.urlopen(req).read()   # Client will get a JSON-encoded status in return
                    print "Status grabbed from: " + username
                    with sqlite3.connect(DB_STRING) as c:
                        c.execute("INSERT INTO user_status(profile_username, status) VALUES (?,?)",
                        [username, json.load(response)]) # store the decoded JSON response
                    return response
                except:
                    return db_calls.checkOnline(username)
        except:
            return "4: Database Error"


    @cherrypy.expose
    def getChatConvo(self, username='entry'):
        conversation = ''
        if (username == 'entry'):  # on first start of app, hardcode conversation
            conversation += '<div class="bubble you">'
            conversation += 'Welcome to fort secure chat!' + '</div>'
            conversation += '<div class="bubble you">'
            conversation += 'To start, choose a user to chat with on the left. <strong>Use the enter key to send.</strong>' + '</div>'
            conversation += '<div class = "bubble you">'
            conversation += 'You can also view user profiles and send/receive files, just use the top navigation bar.' + '</div>'
            conversation += '<div class = "bubble you">'
            conversation += 'Remember to wait at least 10 seconds for your message to appear after sending.' + '</div>'
            conversation += '<div class = "bubble you">'
            conversation += 'You can choose to send your message in <code>markdown </code>too.' + '</div>'
            return str(conversation)
        else:
            # get conversation between somebody and the logged in user.
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT sender, destination, msg, markdown FROM msg ORDER BY stamp ASC")
            for row in cur:
                if (row[3] == 0):  # not a markdown msg
                    if (username == row[0]):  # if the message belongs to the sender, call the div that styles left bubble
                        conversation += '<div class="bubble you">'
                        conversation += row[2] + '</div>'
                    elif (username == row[1]):  # if the message belongs to me, call right bubble
                        conversation += '<div class="bubble me">'
                        conversation += row[2] + '</div>'
                else:
                    markdowner = markdown.Markdown()
                    if (username == row[0]):  # if the message belongs to the sender, call the div that styles left bubble
                        conversation += '<div class="bubble you">'
                        conversation += markdowner.convert(str(row[2])) + '</div>'
                    elif (username == row[1]):  # if the message belongs to me, call right bubble
                        conversation += '<div class="bubble me">'
                        conversation += markdowner.convert(str(row[2])) + '</div>'

            return str(conversation)

    @cherrypy.expose
    def getList(self):
        with sqlite3.connect(DB_STRING) as c:
            c.execute("DELETE FROM user_string")  # in order to avoid dupes in table
        params = {'username':cherrypy.session.get('username'), 'password':cherrypy.session.get('password')}
        full_url = 'http://cs302.pythonanywhere.com/getList?' + urllib.urlencode(params)
        api_call = urllib2.urlopen(full_url).read()
        error_code = api_call[0]  # error code is always first character in string
        api_format = api_call.replace("0, Online user list returned", "")  # remove irrelevant text
        users_online = api_format.count('\n') - 1  # db must insert users_online amount of times
        if (error_code == '0'):
            for i in range(0, users_online):
                data = api_format.split()  # split each user into different list element
                try:  # try to store optional pubkey argument
                    username,location,ip,port,epoch_time,pubkey = data[i].split(",",5)
                    with sqlite3.connect(DB_STRING) as c:
                        c.execute("INSERT INTO user_string(username, location, ip, port, lastlogin, pubkey) VALUES (?,?,?,?,?,?)",
                        [username, location, ip, port, epoch_time, pubkey])
                except:  # if user hasn't implemented pubkey
                    username,location,ip,port,epoch_time = data[i].split(",",4)
                    with sqlite3.connect(DB_STRING) as c:
                        c.execute("INSERT INTO user_string(username, location, ip, port, lastlogin) VALUES (?,?,?,?,?)",
                        [username, location, ip, port, epoch_time])
            return "There are " + str(users_online) + " users online."  # return some useful information on UI
        else:
            return api_call

    @cherrypy.expose
    def logoff(self):
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT username, password FROM user_credentials WHERE username=?",
        [cherrypy.session.get('username')])  # use the user_credentials table
        user_cred = cur.fetchone()
        params = {'username':user_cred[0], 'password':user_cred[1]}
        full_url = 'http://cs302.pythonanywhere.com/logoff?' + urllib.urlencode(params)  # call login server function
        api_call = urllib2.urlopen(full_url).read()
        error_code = api_call[0]
        if (error_code == '0'):
            cherrypy.lib.sessions.expire()  # on success, expire the sessions
            self.logged_on = 3  # prompt to get the right HTML output on logout
            raise cherrypy.HTTPRedirect('/')
        else:
            return api_call

    def logoffForced(self):  # calls on 'application exit' - either server stopping or crashing. see __main__ for use
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT username, password FROM user_credentials")
        credentials = cur.fetchall()
        for i in range(0, len(credentials)):
            params = {'username': credentials[0][0], 'password': credentials[0][1]}
            full_url = 'http://cs302.pythonanywhere.com/logoff?' + urllib.urlencode(params)
            api_call = urllib2.urlopen(full_url).read()
            if api_call.find('0') != -1:  # successful
                return

    @cherrypy.expose
    def ping(self, sender=None):  # Default sender=None so people who don't follow protocol can call
        print("SOMEBODY PINGED YOU!")
        return '0'

    @cherrypy.expose
    def listAPI(self):
        return '/ping /listAPI /receiveMessage [sender] [destination] [message] [stamp] [markdown(opt)]' + \
        '/getProfile [profile_username] [sender] /receiveFile [sender] [destination] [file] [filename]' + \
        '[content_type] [stamp] /getStatus [profile_username]'

    @cherrypy.expose
    @cherrypy.tools.json_in()  # according to docs, all json input parameters stored in cherrypy.request.json
    def receiveMessage(self):  # Note: this function only stores stuff in our tables. Displaying messages is in DisplayMessage
        if LimitReached():  # implements rate limiting to regulate API calls, if true - block user from accessing info
            return 'Error 11: Blacklisted or Rate Limited'
        else:
            try:  # try to receive message with markdown encoding arg
                with sqlite3.connect(DB_STRING) as c:
                    c.execute("INSERT INTO msg(sender, destination, msg, stamp, markdown) VALUES (?,?,?,?,?)",
                    [cherrypy.request.json['sender'], cherrypy.request.json['destination'],
                     cherrypy.request.json['message'], cherrypy.request.json['stamp'], cherrypy.request.json['markdown']])
                print "Message received from " + cherrypy.request.json['sender']
                return '0'
            except:  # if it doesn't work, just store without the markdown encoding argument
                with sqlite3.connect(DB_STRING) as c:
                    c.execute("INSERT INTO msg(sender, destination, msg, stamp, markdown) VALUES (?,?,?,?)",
                    [cherrypy.request.json['sender'], cherrypy.request.json['destination'],
                     cherrypy.request.json['message'], cherrypy.request.json['stamp'], 0])
                print "Message received from " + cherrypy.request.json['sender']
                return '0'

    @cherrypy.expose
    def sendMessage(self, destination, message, markdown):  # this function calls other people's receiveMessage
        # look up the 'destination' user in database and retrieve his corresponding ip address and port
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT ip, port FROM user_string WHERE username=?",[destination])
        values_tuple = cur.fetchall()
        ip = values_tuple[0][0]
        port = values_tuple[0][1]
        if not values_tuple:  # if either ip and port is empty
            return "3: Client Currently Unavailable"
        else:
            try:  # try to send them a message with markdown argument
                output_dict = {"sender": cherrypy.session.get('username'), "message": message,
                "destination": destination, "stamp": int(time.time()), "markdown": markdown}
                postdata = json.dumps(output_dict) # encode to JSON
                req = urllib2.Request("http://" + ip + ":" + port + "/receiveMessage",
                                     postdata, {'Content-Type': 'application/json'})
                try:  # just in case they give an abnormal response, do a try except
                    response = urllib2.urlopen(req).read()
                    if (response.find('0') != -1):  # successfully sent message if '0' is found in return
                        print "Markdown arg message sent to client: " + destination
                        with sqlite3.connect(DB_STRING) as c:  # place our sent message in our table too
                            c.execute("INSERT INTO msg(sender, destination, msg, stamp, markdown) VALUES (?,?,?,?,?)",
                            [cherrypy.session.get('username'), destination, message, int(time.time()), int(markdown)])
                    else:
                        return "4: Database Error"
                except:
                    return "5: Timeout Error"
            except:  # if it doesn't work, try to send them a message without markdown argument
                output_dict = {"sender": cherrypy.session.get('username'), "message": message,
                "destination": destination, "stamp": int(time.time())}
                postdata = json.dumps(output_dict)
                req = urllib2.Request("http://" + ip + ":" + port + "/receiveMessage",
                                     postdata, {'Content-Type': 'application/json'})
                try:
                    response = urllib2.urlopen(req).read()
                    if (response.find('0') != -1):  # successful
                        print "Non-markdown arg message sent to client: " + destination
                        with sqlite3.connect(DB_STRING) as c:
                            c.execute("INSERT INTO msg(sender, destination, msg, stamp) VALUES (?,?,?,?)",  # no markdown arg
                            [cherrypy.session.get('username'), destination, message, int(time.time())])
                    else:
                        return "4: Database Error"
                except:
                    return "5: Timeout Error"
            raise cherrypy.HTTPRedirect("/home")


    @cherrypy.expose
    @cherrypy.tools.json_in()  # profile_username and sender input is stored in cherrypy.request.json
    @cherrypy.tools.json_out(content_type='application/json')  # allows the output to be of type application/json
    def getProfile(self):  # This function called by OTHER people to grab my data only.
    # Use displayProfile to see implementation of displaying profile data, and grabProfile on how to call other's /getProfile
        if LimitReached():  # with every function called by others, check if rate limiting should kick in to stop DDOS's
            return 'Error 11: Blacklisted or Rate Limited'
        else:
            try:
                c = sqlite3.connect(DB_STRING)
                cur = c.cursor()
                cur.execute("SELECT fullname, position, description, location, picture FROM profiles WHERE profile_username=?",
                            [cherrypy.request.json['profile_username']])
                profile_info = cur.fetchone()
                postdata = {"fullname": profile_info[0], "position":profile_info[1],
                            "description":profile_info[2],"location":profile_info[3],
                            "picture":profile_info[4]}
                print("Someone grabbed your profile details!")
                return postdata
            except:
                print("Somebody TRIED to grab your profile details.")
                return "4: Database Error"

    @cherrypy.expose
    def grabProfile(self, profile_username, sender=''):  # this function is called by me (thus no JSON)
    # however a JSON argument will (should) be returned so decoding it before storing in DB is required.
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT ip, port FROM user_string WHERE username=?",
                    [profile_username])
        values = cur.fetchone()
        if not values:  # if search for IP/port comes up empty, target of grab is probably not online
            return '3: Client Currently Unavailable'
        else:
            ip = values[0]
            port = values[1]
            profile_dict = {"profile_username": profile_username, "sender": cherrypy.session.get('username')}
            params = json.dumps(profile_dict)
            req = urllib2.Request("http://" + ip + ":" + port + "/getProfile",
                                 params, {'Content-Type': 'application/json'})
            response = urllib2.urlopen(req).read()
            try:  # if response is not valid JSON, json.loads should throw a ValueError
                print "Profile details grabbed: " + profile_username
                c = sqlite3.connect(DB_STRING)
                cur = c.cursor()
                cur.execute("SELECT profile_username FROM profiles WHERE profile_username=?",
                            [profile_username])
                values = cur.fetchone()  # check if profile grab target is already in database
                if not values:  # if search is empty, insert their details into table
                    with sqlite3.connect(DB_STRING) as c:
                        # decode response
                        response_str = json.loads(response)
                        c.execute("INSERT INTO profiles(profile_username, fullname, position, description, \
                        location, picture) VALUES (?,?,?,?,?,?)",
                        (profile_username, response_str["fullname"], response_str["position"], response_str["description"],
                        response_str["location"], response_str["picture"]))
                    return self.displayProfile(profile_username)
                else:  # they are already in the table, no need to duplicate insert
                    return self.displayProfile(profile_username)
            except ValueError:
                print "An error occurred. The target user is not returning a JSON encoding their profile info."
                return response

    @cherrypy.expose
    def displayProfile(self, user='entry'):
        if (user == 'entry'):  # when page first loads, show the personal profile of the user
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur2 = c.cursor()
            cur.execute("SELECT fullname, position, description, location, picture FROM profiles WHERE profile_username=?",
                        [cherrypy.session.get('username')])
            profile_info = cur.fetchone()
            fullname = profile_info[0]
            position = profile_info[1]
            description = profile_info[2]
            location = profile_info[3]
            picture = profile_info[4]
            cur2.execute("SELECT status FROM user_status WHERE profile_username=?", [cherrypy.session.get('username')])
            status_info = cur2.fetchone()
            status = status_info[0]
            # Also include the edit profile settings in this window
            return '<img src="' + picture + '" height="300" width="300">' + '<br />' + "<b>Full Name: </b> " + str(fullname) + \
            "<b>Position: </b>" + str(position) + "<b>Description: </b>" + str(description) + "<b>Location: </b>" + str(location) + \
            '<br /><b>Status:</b>' + str(status) + """<br /><b>Edit your profile</b><br /><div class="profile-form">
                <form class="update-profile" method = "put" action = "/updateProfile/">
                  <input type="text" placeholder="full name" name = "fullname"/><br />
                  <input type="text" placeholder="position" name = "position"/><br />
                  <input type="text" placeholder="description" name = "description"/><br />
                  <input type="text" placeholder="location" name = "location"/><br />
                  <input type="text" placeholder="picture (URL link)" name = "picture"/><br />
                  <select name = "status">
                      <option selected="selected" disabled="disabled">Set your status</option>
                      <option value="Online">Online</option>
                      <option value="Idle">Idle</option>
                      <option value="Away">Away</option>
                      <option value="Do Not Disturb">Do Not Disturb</option>
                      <option value="Offline">Appear Offline</option>
                  </select>
                <button type = "submit">update</button>
                </form>"""
        else:
            try:
                c = sqlite3.connect(DB_STRING)
                cur = c.cursor()
                cur.execute("SELECT fullname, position, description, location, picture FROM profiles WHERE profile_username=?",
                            [user])
                profile_info = cur.fetchone()
                fullname = profile_info[0]
                position = profile_info[1]
                description = profile_info[2]
                location = profile_info[3]
                picture = profile_info[4]
                return '<br /><img src="' + picture + '" height="300" width="300">' + '<br />' + \
                '<div class = "bubble you">' + '<b>Full Name:</b> ' + str(fullname) + '<br /></div>' + \
                '<div class = "bubble you">' + '<b>Position:</b> ' + str(position) + '<br />' + \
                '<b>Description:</b> ' + str(description) + '<br />' + "<b>Location:</b> " + str(location) + \
                '<br /></div>'
            except:
                return '<div class="bubble you">This profile has not published any information yet.</div>'

    @cherrypy.expose
    def updateProfile(self, fullname, position, description, location, picture, status):
        # is called when displayProfile's form is submitted
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("""
        UPDATE profiles SET fullname=?,position=?,description=?,location=?,picture=? WHERE profile_username=?""",
        (fullname, position, description, location, picture, cherrypy.session.get('username')))
        c.commit()  # thank you stack overflow
        self.setStatus(status)
        raise cherrypy.HTTPRedirect("/viewProfiles")

    @cherrypy.expose
    @cherrypy.tools.json_in()  # takes in sender, destination, file, filename, content_type, stamp
    def receiveFile(self):
        try:
            with sqlite3.connect(DB_STRING) as c:  # insert everything into my table. It is sender's job to base64
                c.execute("INSERT INTO files(sender, destination, file, filename, content_type, stamp) VALUES (?,?,?,?,?,?)",
                [cherrypy.request.json['sender'], cherrypy.request.json['destination'], cherrypy.request.json['file'],
                cherrypy.request.json['filename'], cherrypy.request.json['content_type'], cherrypy.request.json['stamp']])
            print ("Received file from: " + str(cherrypy.request.json['sender']))
            return '0'
        except:
            return 'An error occurred'

    @cherrypy.expose
    def sendFile(self, destination, file):  # get filename and content_type from uploaded file
        try:
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT ip, port FROM user_string WHERE username=?",[destination])
            values = cur.fetchone() # get ip and port of target user
            ip = values[0]
            port = values[1]
        except:
            return "3: Client Currently Unavailable"

        file_dict = {"sender": cherrypy.session.get('username'), "destination": destination,
        "file": base64.b64encode(file.file.read()), "filename": str(file.filename),
        "content_type": str(file.content_type), "stamp": int(time.time())}
        params = json.dumps(file_dict)
        req = urllib2.Request("http://" + ip + ":" + port + "/receiveFile",
              params, {'Content-Type': 'application/json'})
        response = urllib2.urlopen(req).read()
        if (response.find('0') != -1):  # successful
            print ("Sent file to " + str(destination))
            raise cherrypy.HTTPRedirect("/files")
        else:
            return 'The user has not reported that the file send was successful.'

    @cherrypy.expose
    def displayFile(self):  # display contents of database - 'embedded media player' here
        try:
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT sender, file, filename, content_type, stamp FROM files WHERE destination=?",
            [cherrypy.session.get('username')])
            file_list = cur.fetchall()
            files = ''
            for i in range(0, len(file_list)):
                # The following code helps format data in our files table into HTML tags for embedded media display
                if ("image/" in str(file_list[i][3])): # if file has mimetype starting with 'image/'...
                    files += '<div class="bubble you">' + 'From: ' + '<b>' + str(file_list[i][0]) + '</b><br />' +  \
                    '<br /><img alt="image" height="120" width="120" src="data:' + str(file_list[i][3]) + ';base64,' + str(file_list[i][1]) + '"><br />' + \
                    'Name: ' + str(file_list[i][2]) + '<br />' + 'Type: ' + str(file_list[i][3]) + '<br />' + \
                    'Time sent: ' + time_formatting.epochFormat(file_list[i][4]) + '<br /><br /></div>'
                elif ("video/" in str(file_list[i][3])):  # if file has mimetype starting with 'video/'
                    files += '<div class="bubble you">' + 'From: ' + '<b>' + str(file_list[i][0]) + '</b><br />' + \
                    '<br /><video height="300" width="300" controls><source type="' + str(file_list[i][3]) + '"src="data:' + str(file_list[i][3]) + \
                    ';base64,' + str(file_list[i][1]) + '"></video>' + '<br /> Name: ' + str(file_list[i][2]) + '<br /> Type: ' + \
                    str(file_list[i][3]) + '<br /> Time sent: ' + time_formatting.epochFormat(file_list[i][4]) + '<br /><br /></div>'
                elif ("audio/" in str(file_list[i][3])):  # if file has mimetype starting with 'audio/'
                    files += '<div class="bubble you">' + 'From: ' + '<b>' + str(file_list[i][0]) + '</b><br />' + \
                    '<br /><audio controls src="data:' + str(file_list[i][3]) + ';base64,' + str(file_list[i][1]) + '"></audio>' + \
                    '<br />Name: ' + str(file_list[i][2]) + '<br />' + 'Type: ' + str(file_list[i][3]) + '<br />' + \
                    'Time sent: ' + time_formatting.epochFormat(file_list[i][4]) + '<br /><br /></div>'
                else:  # provide a download link (to say, PDFs)
                    files += '<div class="bubble you">' + 'From: ' + '<b>' + str(file_list[i][0]) + '</b><br />' + \
                    '<br /><a download href="data:' + str(file_list[i][3]) + ';base64,' + str(file_list[i][1]) + '">Download ' + \
                    str(file_list[i][2]) + '</a>' + '<br />Name: ' + str(file_list[i][2]) + '<br />' + 'Type: ' + \
                    str(file_list[i][3]) + '<br />' + 'Time sent: ' + time_formatting.epochFormat(file_list[i][4]) + '<br /><br /></div>'
            if not files:  # no files were found
                return 'No files were found.'
            return files
        except:
            return 'An error occurred when attempting to display files'

    @cherrypy.expose
    def displayFileForm(self):  # created so sending files could run through an AJAX request. Links to /sendFile
        return """<br /><br /><br /><br />
            <br /><br /><br /><br /><div class="form">
            <form class="login-form" method = "post" action = "/sendFile/" enctype="multipart/form-data">
              <input type="text" placeholder="recipient of file" name = "destination"/>
              <input type="file" name = "file"/>
            <button type = "submit" value="Send">send file!</button>
            </form>"""

    @cherrypy.expose
    def displayReceivedMessage(self):  # This is called in message logs to display ALL received messages, with timestamps
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT sender, msg, stamp FROM msg WHERE destination=?",
        [cherrypy.session.get('username')])
        msg_list = cur.fetchall()
        messages = ''
        for i in range(0, len(msg_list)):
            messages += '<i><b>' + str(msg_list[i][0]) + '</b>' + " [" + time_formatting.epochFormat(msg_list[i][2]) + "]" + \
            " (" + str(time_formatting.timeSinceMessage(msg_list[i][2])) + ")" + " messaged you: " + str(msg_list[i][1]) + "<br /></i>"
        return messages

    @cherrypy.expose
    def displaySentMessage(self):  # Called in message logs page to display ALL sent messages, with timestamps
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT destination, msg, stamp FROM msg WHERE sender=?",
        [cherrypy.session.get('username')])
        msg_list = cur.fetchall()
        messages = ''
        for i in range(0, len(msg_list)):
            messages += '<i><b>You sent ' + str(msg_list[i][0]) + ':</b>' + " [" + time_formatting.epochFormat(msg_list[i][2]) + "]"\
            " (" + str(time_formatting.timeSinceMessage(msg_list[i][2])) + ")" + ": " + str(msg_list[i][1]) + "<br /></i>"
        return messages

    @cherrypy.expose
    def searchMessage(self, msg_phrase):
        # Is called upon search query in message logs. Returns all messages (sent or received) that contains the search query.
        # Note that it is case insensitive, and also does not require an exact word match; a result matches even if the query
        # is part of a larger word. This is probably most practical for message searching purposes

        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT sender, destination, msg, stamp FROM msg WHERE msg LIKE ('%' || ? || '%')", [msg_phrase])
        msg_list = cur.fetchall()
        messages = ''
        for i in range(0, len(msg_list)):
            if msg_list[i][0] == cherrypy.session.get('username'):  # if the msg is a sent message
                messages += '<i><b>You sent ' + str(msg_list[i][1]) + ':</b>' + " [" + time_formatting.epochFormat(msg_list[i][3]) + "]"\
                " (" + str(time_formatting.timeSinceMessage(msg_list[i][3])) + ")" + ": " + str(msg_list[i][2]) + "<br /></i>"
            else:  # msg is a received message
                messages += '<i><b>' + str(msg_list[i][0]) + '</b>' + " [" + time_formatting.epochFormat(msg_list[i][3]) + "]" + \
                " (" + str(time_formatting.timeSinceMessage(msg_list[i][3])) + ")" + " messaged you: " + str(msg_list[i][2]) + "<br /></i>"
        if not messages:
            return 'No messages found for the term: ' + msg_phrase
        else:
            return messages

conf = {
        '/': {
            'tools.sessions.on': True,
            'tools.staticdir.on': True,
            'tools.staticdir.dir': os.path.abspath(os.path.dirname(__file__)),
            'tools.staticdir.root': os.path.dirname(os.path.abspath(__file__))
        },
        '/static': {
            'tools.staticdir.on': True,
            'tools.staticdir.dir': './public'
        }
    }

if __name__ == '__main__':
    try:
        cherrypy.config.update({'server.socket_host': listen_ip,
                                'server.socket_port': listen_port,
                                'tools.staticdir.debug': True,
                                'engine.autoreload.on': True,
                                'tools.gzip.on': True,
                                'tools.gzip.mime_types': ['text/*'],
                                })
        cherrypy.tree.mount(MainApp(), '/', conf)
        cherrypy.engine.start()
        cherrypy.engine.block()
    finally:  # on application exit
        MainApp().logoffForced()  # uses user_credentials table to forcefully log off user
