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
import encrypt
from cherrypy.process.plugins import Monitor

DB_STRING = "users.db"
reload(sys)
sys.setdefaultencoding('utf8')
listen_ip = '192.168.20.2'# socket.gethostbyname(socket.getfqdn())
listen_port = 10002
api_calls = 0

def resetTimer():
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
    blacklist = cur.fetchone()
    if blacklist:  # if users were found on the blacklist
        for i in range(0, len(blacklist)):  # search through the list
            if ip == blacklist[i]:  # a match was found with the calling ip and somebody in the blacklist
                print("A blacklisted user tried to call your functions")
                return True
    global api_calls
    api_calls = api_calls + 1
    print('Current calls:' + str(api_calls))
    if (api_calls > 10):  # if 11 people have called my functions within 60 seconds
        print("Rate limit activated, a user was blocked from your API")
        return True  #  block the request and return Error 11: Blacklisted or Rate Limited (done in other funcs)
    else:
        return False # let the user have the information

class MainApp(object):
    logged_on = 0  # 0 = never tried to log on, 1 = success, 2 = tried and failed, 3 = success and logged out

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
            return "You are not logged in. Click " + "<a href='/'>here</a> to login"
        data = data.replace("USERS_ONLINE", self.getList())
        data = data.replace("LIST_OF_TOTAL_USERS", self.listAllUsers())
        data = data.replace("RECEIVED_MESSAGE_LIST", self.displayReceivedMessage())
        data = data.replace("SENT_MESSAGE_LIST", self.displaySentMessage())
        data = data.replace("PLACEHOLDER", self.getChatConvo())
        return data

    @cherrypy.expose
    def myProfile(self):
        f = open("myProfile.html", "r")
        data = f.read()
        f.close()
        try:
            data = data.replace("USER_NAME", cherrypy.session.get('username'))
        except:
            return "You are not logged in. Click " + "<a href='/'>here</a> to login"
        data = data.replace("PROFILE_DETAILS", self.displayProfile())
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
        if (self.file_sent == 1):
            data = data.replace("FILE_STATUS", "File successfully sent.")
        else:
            data = data.replace("FILE_STATUS", "")
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

    @cherrypy.expose
    def twoFA(self):
        f = open("twoFA.html", "r")
        data = f.read()
        f.close()
        data = data.replace("GAUTH_KEY",encrypt.secret)
        return data

    @cherrypy.expose
    def validate2FA(self, code):
        # edge case if MSB of code is 0, get_totp_token would return a 5 digit no.
        if code[0] == '0':
            code = code[1:]  # new code doesnt include MSB

        if (int(code) == encrypt.get_totp_token(encrypt.secret)):
            print("twoFA successfully authenticated")
            with sqlite3.connect(DB_STRING) as c:
                c.execute("INSERT INTO user_credentials(username, password, location, ip, port) VALUES (?,?,?,?,?)",
                [cherrypy.session.get('username'), cherrypy.session.get('password'), cherrypy.session.get('location'),
                cherrypy.session.get('ip'),cherrypy.session.get('port')])
            raise cherrypy.HTTPRedirect('/home')
        else:
            self.logged_on = 2
            cherrypy.lib.sessions.expire()
            raise cherrypy.HTTPRedirect('/')

    @cherrypy.expose
    def report(self, username, password, location='2', ip='180.148.100.178', port=listen_port):  # change ip = back to listen_ip
        # print(ip)
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
            else:  # could find user, go straight to /home without needing 2FA
                raise cherrypy.HTTPRedirect('/home')
        else:
            print("ERROR: " + error_code)
            self.logged_on = 2
            raise cherrypy.HTTPRedirect('/')  # set flag to change /index function

    def reportThreaded(self):
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT username, password, location, ip, port FROM user_credentials")
        credentials = cur.fetchone()
        auth = self.authoriseUserLogin(credentials[0],credentials[1],credentials[2],credentials[3],credentials[4])
        print("/report called!")
        print(auth)
        return auth

    @cherrypy.expose
    def blackList(self, choice, username):
        if choice == 'Block':  # if user chose Block from dropdown
            c = sqlite3.connect(DB_STRING) # to find the IP address of the blocked user, search the
            cur = c.cursor()
            cur.execute("SELECT ip FROM user_string WHERE username=?", [username])
            creds = cur.fetchone()
            if not creds:  # couldn't found username's IP address
                return 'IP not found, user may not be online. Click ' + '<a href="/home">here</a> to go back.'
            else:
                with sqlite3.connect(DB_STRING) as c:
                    c.execute("INSERT INTO blacklist(username, ip) VALUES (?,?)",
                    [username,creds[0]])
        else: # Unblock was chosen
            with sqlite3.connect(DB_STRING) as c:
                c.execute("DELETE FROM blacklist WHERE username=?", [username])
        raise cherrypy.HTTPRedirect('/home')  # refresh the page


    @cherrypy.expose
    def listAllUsers(self):
        with sqlite3.connect(DB_STRING) as c:
            c.execute("DELETE FROM total_users")  # in order to avoid dupes in table
        url = 'http://cs302.pythonanywhere.com/listUsers'
        api_call = urllib2.urlopen(url).read()
        total_users_list = api_call.split(",")
        total_users = len(total_users_list)
        total_users_string = ''
        for i in range(0, total_users):
            if total_users_list[i] != cherrypy.session.get('username'):  # don't add the current user to list of possible contacts
                with sqlite3.connect(DB_STRING) as c:
                    c.execute("INSERT INTO total_users(username) VALUES (?)",
                    [total_users_list[i]])
                total_users_string += '<li class="person">' + \
                '<img src="' + self.getProfilePic(total_users_list[i]) + '"/>' + '<span class="name">' + \
                str(total_users_list[i]) + '</span>' + \
                '<span class="preview">' + self.checkOnline(total_users_list[i]) + '</span></li>'
        return total_users_string

    def getProfilePic(self, user):
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT picture FROM profiles WHERE profile_username=?",
                    [user])
        pic = cur.fetchone()
        if not pic:  # no pic found
            return 'http://imgur.com/oymng0G.jpg'  # return default pic, fort logo
        else:
            return ''.join(pic)  # tuple to string

    def checkOnline(self, user):
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT lastlogin FROM user_string WHERE username=?", [user])
        credentials = cur.fetchone()
        if not credentials:  # empty found
            return ''
        else:
            return 'Online now!'


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
                print("Someone grabbed your profile status!")
                return json.dumps(credentials[0])  # return out a JSON encoded string
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
                return 'Offline'
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
                    return self.checkOnline(username)
        except:
            return "Error grabbing status data"


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
            conversation += 'You can choose to send your message <em>in </em><code>markdown </code>too.' + '</div>'
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
            return "There are " + str(users_online) + " users online."
        else:
            return api_call

    @cherrypy.expose
    def logoff(self):
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT username, password FROM user_credentials WHERE username=?",
        [cherrypy.session.get('username')])
        user_cred = cur.fetchone()
        params = {'username':user_cred[0], 'password':user_cred[1]}
        full_url = 'http://cs302.pythonanywhere.com/logoff?' + urllib.urlencode(params)
        api_call = urllib2.urlopen(full_url).read()
        error_code = api_call[0]
        if (error_code == '0'):
            cherrypy.lib.sessions.expire()
            self.logged_on = 3
            raise cherrypy.HTTPRedirect('/')
        else:
            return api_call

    def logoffForced(self):
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
    def ping(self):  # for other people to check me out, implement sender arg later
        print("SOMEBODY PINGED YOU!")
        return '0'

    @cherrypy.expose
    def listAPI(self):
        return '/ping /listAPI /receiveMessage [sender] [destination] [message] [stamp] [markdown(opt)]' + \
        '/getProfile [profile_username] [sender] /receiveFile [sender] [destination] [file] [filename]' + \
        '[content_type] [stamp] /getStatus [profile_username]'

    @cherrypy.expose
    @cherrypy.tools.json_in()  # according to docs, all json input parameters stored in cherrypy.request.json
    def receiveMessage(self):
        if LimitReached():  # implements rate limiting to regulate API calls, if true - block user from accessing info
            return 'Error 11: Blacklisted or Rate Limited'
        else:  # continue on with life
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
    def sendMessage(self, destination, message, markdown):
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
                postdata = json.dumps(output_dict)
                req = urllib2.Request("http://" + ip + ":" + port + "/receiveMessage",
                                     postdata, {'Content-Type': 'application/json'})
                try:
                    response = urllib2.urlopen(req).read()
                    if (response.find('0') != -1):  # successful
                        print "Markdown arg message sent to client: " + destination
                        with sqlite3.connect(DB_STRING) as c:
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
    @cherrypy.tools.json_out(content_type='application/json')  # allows the output to be of type application/json instead of text/html
    def getProfile(self):  # this function is called by OTHER people to grab my data. use displayProfile to see my own, grabProfile to get others
        if LimitReached():
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
    def grabProfile(self, profile_username, sender=''):  # this function is called by me
        try:  # first try to fetch data from the local database, if we have something
            return self.displayProfile(profile_username) # REMOVE THIS LATER... WE WANT THE LATEST PROFILE INFO!!
        except:  # if we don't, then try to call their /getProfile to store, then do step 1
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT ip, port FROM user_string WHERE username=?",
                        [profile_username])
            values = cur.fetchone()
            if not values:
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
                            c.execute("INSERT INTO profiles(profile_username, fullname, position, description, location, picture) VALUES (?,?,?,?,?,?)",
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
        if (user == 'entry'):
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
                "<br /></div>Status: "
                # + self.grabStatus(user)
            except:
                return '<div class="bubble you">This profile has not published any information yet.</div>'

    @cherrypy.expose
    def updateProfile(self, fullname, position, description, location, picture, status):
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
            with sqlite3.connect(DB_STRING) as c:
                c.execute("INSERT INTO files(sender, destination, file, filename, content_type, stamp) VALUES (?,?,?,?,?,?)",
                [cherrypy.request.json['sender'], cherrypy.request.json['destination'], cherrypy.request.json['file'],
                cherrypy.request.json['filename'], cherrypy.request.json['content_type'], cherrypy.request.json['stamp']])
            print ("Received file from: " + str(cherrypy.request.json['sender']))
            return '0'
        except:
            return 'An error occurred'

    file_sent = 0

    @cherrypy.expose
    def sendFile(self, destination, file):  # get filename and content_type from uploaded file
        #get ip and port of target user
        try:
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT ip, port FROM user_string WHERE username=?",[destination])
            values_tuple = cur.fetchone()
            ip = values_tuple[0]
            port = values_tuple[1]
        except:
            return "3: Client Currently Unavailable"
        # check if their listAPI contains receiveFile, or the function won't work
        # if (self.checkListAPI(destination, 'receiveFile')): # if they do have receiveFile
        file_dict = {"sender": cherrypy.session.get('username'), "destination": destination, "file": base64.b64encode(file.file.read()),
                    "filename": str(file.filename), "content_type": str(file.content_type), "stamp": int(time.time())}
        print(file_dict)
        params = json.dumps(file_dict)
        req = urllib2.Request("http://" + ip + ":" + port + "/receiveFile",
              params, {'Content-Type': 'application/json'})
        response = urllib2.urlopen(req).read()
        if (response.find('0') != -1):  # successful
            print ("Sent file to " + str(destination))
            self.file_sent = 1
            raise cherrypy.HTTPRedirect("/files")

        else:
            self.file_sent = 0
            return 'The user has not reported that the file send was successful.'
        # else: # no receiveFile
        #     return 'This user has not implemented receiveFile yet'

    @cherrypy.expose
    def displayFile(self):
        try:
            c = sqlite3.connect(DB_STRING)
            cur = c.cursor()
            cur.execute("SELECT sender, file, filename, content_type, stamp FROM files WHERE destination=?",
            [cherrypy.session.get('username')])
            file_list = cur.fetchall()
            files = ''

            for i in range(0, len(file_list)):
                # if file has mimetype starting with 'image/', use <img> tag to display
                if ("image/" in str(file_list[i][3])):
                    files += '<div class="bubble you">' + 'From: ' + '<b>' + str(file_list[i][0]) + '</b><br />' +  \
                    '<br /><img alt="image" height="120" width="120" src="data:' + str(file_list[i][3]) + ';base64,' + str(file_list[i][1]) + '"><br />' + \
                    'Name: ' + str(file_list[i][2]) + '<br />' + 'Type: ' + str(file_list[i][3]) + '<br />' + \
                    'Time sent: ' + self.epochFormat(file_list[i][4]) + '<br /><br /></div>'
                elif ("video/" in str(file_list[i][3])):
                    files += '<div class="bubble you">' + 'From: ' + '<b>' + str(file_list[i][0]) + '</b><br />' + \
                    '<br /><video height="300" width="300" controls><source type="' + str(file_list[i][3]) + '"src="data:' + str(file_list[i][3]) + \
                    ';base64,' + str(file_list[i][1]) + '"></video>' + '<br /> Name: ' + str(file_list[i][2]) + '<br /> Type: ' + \
                    str(file_list[i][3]) + '<br /> Time sent: ' + self.epochFormat(file_list[i][4]) + '<br /><br /></div>'
                elif ("audio/" in str(file_list[i][3])):
                    files += '<div class="bubble you">' + 'From: ' + '<b>' + str(file_list[i][0]) + '</b><br />' + \
                    '<br /><audio controls src="data:' + str(file_list[i][3]) + ';base64,' + str(file_list[i][1]) + '"></audio>' + \
                    '<br />Name: ' + str(file_list[i][2]) + '<br />' + 'Type: ' + str(file_list[i][3]) + '<br />' + \
                    'Time sent: ' + self.epochFormat(file_list[i][4]) + '<br /><br /></div>'
                else:  # provide a download link (to say, PDFs)
                    files += '<div class="bubble you">' + 'From: ' + '<b>' + str(file_list[i][0]) + '</b><br />' + \
                    '<br /><a download href="data:' + str(file_list[i][3]) + ';base64,' + str(file_list[i][1]) + '">Download ' + \
                    str(file_list[i][2]) + '</a>' + '<br />Name: ' + str(file_list[i][2]) + '<br />' + 'Type: ' + \
                    str(file_list[i][3]) + '<br />' + 'Time sent: ' + self.epochFormat(file_list[i][4]) + '<br /><br /></div>'
            if not files:  # no files were found
                return 'No files were found.'
            return files
        except:
            return 'An error occurred when attempting to display files'

    @cherrypy.expose
    def displayFileForm(self):
        return """<br /><br /><br /><br />
            <br /><br /><br /><br /><div class="form">
            <form class="login-form" method = "post" action = "/sendFile/" enctype="multipart/form-data">
              <input type="text" placeholder="recipient of file" name = "destination"/>
              <input type="file" name = "file"/>
            <button type = "submit" value="Send">send file!</button>
            </form>"""

    @cherrypy.expose
    def displayReceivedMessage(self):
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT sender, msg, stamp FROM msg WHERE destination=?",
        [cherrypy.session.get('username')])
        msg_list = cur.fetchall()
        messages = ''
        for i in range(0, len(msg_list)):
            messages += '<i><b>' + str(msg_list[i][0]) + '</b>' + " [" + self.epochFormat(msg_list[i][2]) + "]" + \
            " (" + str(self.timeSinceMessage(msg_list[i][2])) + ")" + " messaged you: " + str(msg_list[i][1]) + "<br /></i>"
        return messages

    @cherrypy.expose
    def checkListAPI(self, username, string):
        # this function calls the user's /listAPI looking for the string.
        # the function returns True if the string is found, and False if the string is not found.
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT ip, port FROM user_string WHERE username=?",[username])
        values_tuple = cur.fetchone()
        api_call = 'http://' + values_tuple[0] + ':' + values_tuple[1] + '/listAPI'
        response = urllib2.urlopen(api_call).read()
        if response.find(string) != -1:  # successful in finding string
            return True
        else:
            return False

    @cherrypy.expose
    def displaySentMessage(self):
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT destination, msg, stamp FROM msg WHERE sender=?",
        [cherrypy.session.get('username')])
        msg_list = cur.fetchall()
        messages = ''
        for i in range(0, len(msg_list)):
            messages += '<i><b>You sent ' + str(msg_list[i][0]) + ':</b>' + " [" + self.epochFormat(msg_list[i][2]) + "]"\
            " (" + str(self.timeSinceMessage(msg_list[i][2])) + ")" + ": " + str(msg_list[i][1]) + "<br /></i>"
        return messages

    @cherrypy.expose
    def searchMessage(self, msg_phrase):
        c = sqlite3.connect(DB_STRING)
        cur = c.cursor()
        cur.execute("SELECT sender, destination, msg, stamp FROM msg WHERE msg LIKE ('%' || ? || '%')", [msg_phrase])
        msg_list = cur.fetchall()
        messages = ''
        for i in range(0, len(msg_list)):
            if msg_list[i][0] == cherrypy.session.get('username'):  # if the msg is a sent message
                messages += '<i><b>You sent ' + str(msg_list[i][1]) + ':</b>' + " [" + self.epochFormat(msg_list[i][3]) + "]"\
                " (" + str(self.timeSinceMessage(msg_list[i][3])) + ")" + ": " + str(msg_list[i][2]) + "<br /></i>"
            else:  # msg is a received message
                messages += '<i><b>' + str(msg_list[i][0]) + '</b>' + " [" + self.epochFormat(msg_list[i][3]) + "]" + \
                " (" + str(self.timeSinceMessage(msg_list[i][3])) + ")" + " messaged you: " + str(msg_list[i][2]) + "<br /></i>"
        if not messages:
            return 'No messages found for the term: ' + msg_phrase
        else:
            return messages


    def jsonEncodeMessage(self, sender, message, destination, stamp, markdown):

        return data

    def epochFormat(self, timeStamp):
        return datetime.datetime.fromtimestamp(timeStamp).strftime('%Y-%m-%d %H:%M:%S').encode('ascii', 'ignore')

    def timeSinceMessage(self, timeStamp):
        timeSince = time.time() - timeStamp
        units = ''
        if timeSince < 60:
            timeSince = int(round(timeSince))
            units = ' second(s) ago'
        elif timeSince >= 60 and timeSince < 3600:
            timeSince = int(round(timeSince / 60))
            units = ' minute(s) ago'
        elif timeSince >= 3600 and timeSince < 86400:
            timeSince = int(round(timeSince / 3600))
            units = ' hour(s) ago'
        elif timeSince >= 86400 and timeSince < 604800:
            timeSince = int(round(timeSince / 86400))
            units = ' day(s) ago'
        else:
            return "A very long time ago"
        return str(timeSince) + units

    def authoriseUserLogin(self,username, password, location, ip, port):
        params = {'username':username, 'password':password, 'location':location, 'ip':ip, 'port':port}
        full_url = 'http://cs302.pythonanywhere.com/report?' + urllib.urlencode(params)  # converts to format &a=b&c=d...
        return urllib2.urlopen(full_url).read()


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
        MainApp().logoffForced()
