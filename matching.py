# -*- coding: utf-8 -*-

"""
Improve:
    Google returns no matches for many photos. We can use additional photos beyond the first 4.
    Tineye requires an API key
    Berify is another provider at $150/month
    
    
    Description searches: usually a listing's main description is just copied.
        It looks very promising. Pick about 20 words from description. Can use site:www.vrbo.com "description"
        then the first hit is almost certainly the right one. Plan this in for the next sweep of the data in which
        images 4,5,6 will be used as well as text
        
        example:
        https://www.google.com/search?num=100&ei=2BeiW7TNMoWjzwLT34jgBw&q=site%3Awww.vrbo.com+%22Your+private+oasis+awaits+you+in+the+Master+suite.+It+has+a+plush+Queen+sized+bed+and+flat+screen+TV.+Start+your+day+the+perfect%22

    Some of those most difficult to link by other means have a dead giveaway in the title. e.g. 
        Island Surf 404
        Kamaole Sands 5-313 ...
        Maui Sunset B402- ...
        Maui Banyan Q204 2 bed/2 bath...
        
    Some have a tax ID
        Tax ID # TA-069-528-3712-01
        
"""

import time, os.path, csv, sys, datetime
import datetime, threading, csv, re
import glob
import json
import gspread
import random
from oauth2client.client import OAuth2WebServerFlow
from oauth2client.tools import run_flow
from oauth2client.tools import argparser
from oauth2client.file import Storage
# Python 3 compatibility
try:
    import urlparse
except ImportError:
    import urllib.parse as urlparse

import requests
import urllib

global today_count, alltime_count, last_sent
global sheets, sc, credentials

USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/31.0.1650.57 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9) AppleWebKit/537.71 (KHTML, like Gecko) Version/7.0 Safari/537.71',
    'Mozilla/5.0 (Windows NT 6.1; WOW64; rv:25.0) Gecko/20100101 Firefox/25.0',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/31.0.1650.57 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/30.0.1599.101 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.1) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/31.0.1650.57 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.9; rv:25.0) Gecko/20100101 Firefox/25.0',
    'Mozilla/5.0 (Windows NT 6.2; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/31.0.1650.57 Safari/537.36',
    'Mozilla/5.0 (Windows NT 6.3; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/31.0.1650.57 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_9_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/30.0.1599.101 Safari/537.36',
]

ota=['homeaway.','airbnb.','vrbo.']

GOOGLE_SEARCH_BY_ENDPOINT = 'http://images.google.com/searchbyimage?hl=en&num=20&image_url='
GOOGLE_TEXTSEARCH_ENDPOINT = 'http://www.google.com/search?num=10&q='
G_SHEET = '19kwkFestzeZxRkbYc6c63cVf-S7PQKv4qvQCuJpJseo'

def main():
    global credentials
    
    credentials = ""
    sheets_init()
    
    alocation = -1
    while alocation:
        psheet = sheets.worksheet("progress")
        allocation = psheet.acell('B1').value
        # immediately increase the next allocation number
        nextup = str(int(allocation)+1)
        psheet.update_acell('B1', nextup)
        
        asheet = sheets.worksheet("active")
        hc_link = asheet.acell('B' + str(allocation)).value
        if not hc_link: break
        manualb = asheet.acell('G' + str(allocation)).value #vrbo
        if manualb == "0" : manualb = ""
        manuala = asheet.acell('H' + str(allocation)).value #abb
        if manuala == "0":  manuala = ""
        autoa = asheet.acell('I' + str(allocation)).value
        autoa_score = asheet.acell('J' + str(allocation)).value
        if autoa_score: autoa_score = float(autoa_score)
        else: autoa_score = 99.0   # populate the Prop object to ensure that I don't overwrite a good match with a poorer one.

        autob = asheet.acell('K' + str(allocation)).value
        autob_score = asheet.acell('L' + str(allocation)).value
        if autob_score: autob_score = float(autob_score)
        else: autob_score = 99.0
        
        if manuala and manualb: 
            print "already filled data manually for ",hc_link
            continue    # no need to match those already matched by hand.
        if  manualb and (autoa and autoa_score < 3.0): 
            print "already got data in G and I for ",hc_link
            continue
        if  manuala and (autob and autob_score < 3.0): 
            print "already got data in H and K for", hc_link
            continue
        if (autoa and autoa_score < 3.0) and (autob and autob_score < 3.0): continue
        if len(hc_link) < 10:
            # all done
            allocation = 0
            
        prop = do_hc_link(hc_link)
        prop.set_scores(autoa,autoa_score,autob,autob_score)
        hcid = hc_link.split("/")[-1]
        
        likely = []  # likely links collected from both page search and reverse image search
        # start with a text search for vrbo/airbnb pages:
        pagetext = prop.get_text()
        # take first 10 words of summary and first 10 words of description
        pt =  pagetext.split("|")
        pt0 = " ".join(pt[0].split(" ")[:10])
        pt1 = " ".join(pt[1].split(" ")[:10])
        pt2 = " ".join(pt[2].split(" ")[:10])
        # form search string and do normal google searches restricted to VRBO and ABB sites
        searchphrase =  pt0 + ' "' + pt1 + '" ' + pt2
        searchtext = 'site:www.vrbo.com '+ searchphrase
        likely = googlesearch(searchtext,hcid,"vrbo")
        searchtext = 'site:www.airbnb.com '+ searchphrase
        likely.extend( googlesearch(searchtext,hcid,"abb"))
        likely = clean_links(likely)
        
        # in this loop, we assess progress after each image and stop before the limit if we have success
        for i,image in enumerate(prop.images[:4]):
            newlinks= try_matching(image,hcid,i)   # returns list of likely matches
            if newlinks: likely.extend(newlinks)
            likely.append("") # an empty link, so that I can know which links came from which image as one image may be generic
            decided = assess_links(likely, prop)
            if decided > 1: break
            
        update_sheet(prop, allocation)
        
def googlesearch(searchtext, hcid,site):

    searchtext = urllib.quote_plus(searchtext)
    
    result_url = GOOGLE_TEXTSEARCH_ENDPOINT + searchtext
    referer = 'http://www.google.com/'
    result_html = fire_request(result_url, referer)
    with open("temp_"+hcid+"_" + site + ".html","wb") as output:  # debug/monitoring output files
        output.write(to_ascii(result_html))
    links = []
    
    links = findbetween( result_html,'<a href="', '"', 'Search Results</h1>',multi=True  )[:4]
    #print "googlesearch returned:",links
    return links
            
def try_matching(image,hcid,imgno):
    # called once per image to be matched
    gpage = search_by(image,hcid,imgno)
    while "captcha" in gpage.lower():
        ohshitcaptcha()
        gpage = search_by(image,hcid,imgno)
        
    links = findbetween(gpage,'"r"><a href="','"',"include matching images",True)


    
    #print "Initial image matches:",len(links)
    for l in links: print l

    return clean_links(links)
    
def clean_links(links):

    vrbonums = []
    for l in links:   # vrbo/homeaway can give us several equivalent links. If there's a VRBO link, kill all others with the same number
        if "vrbo" in l:
            word = l.split('/')[-1]
            vrbonums.append( alldigits(word) )

    for i in range(len(links)):
        l = links[i]
        keep = 0
        for b in ota:
            if b in l: keep = 1
        if not keep: links[i] = ""
        # signs of a good link: < 60 characters, lacks "?", 
        if len(l) > 60 or "?" in l: links[i] = ""
        
        word = l.split('/')[-1]
        nbr = alldigits(word)
        
        if len(nbr) < 3: links[i] = ""    # kills any which don't have a mainly numerical property ID

        if nbr in vrbonums and not "vrbo" in l: links[i] = ""  # removing non-vrbo equivalents of a VRBO link that we've got
        
    links = [l for l in links if len(l)>0]
    #print "Final image matches:",len(links)
    # remove duplicates
    links = list(set(links))
    
    
    for l in links: print l
    return links
    

def assess_links(links, prop):
    # An array of links. Can we tell, just by looking at the URLs, what the Airbnb and/or VRBO equivalents of this listing are?
    # the links array contain just those that look right (vrbo, homeaway, airbnb)
    
    vrbos = {}  # in these, just put the numeric part of any property ID as key. Value is blank to start
    abbs = {}
    imgcount = 0
    for l in links:
        if l == "":
            imgcount += 1   # Will allow removal of matches one image batch at a time.
            continue
            
        word = l.split('/')[-1]
        nbr = alldigits(word)
        if len(nbr) > 2:
            if ("vrbo" in l or "homeaway" in l) and not word.startswith("r"):  # avoiding "Region" pages on vrbo
                if vrbos.has_key(nbr):
                    vrbos[nbr] += 1
                else:      
                    vrbos[nbr] = 1
            if "airbnb" in l:
                if abbs.has_key(nbr):
                    abbs[nbr] += 1
                else:      
                    abbs[nbr] = 1
    
    # if it went very well, there should be just one item (or none) in each dict but we allow multiple to be filtered by other means
    if len(vrbos) >0 or len(abbs) > 0:
        #print "something appears to match"
        for vrbomatch in vrbos.keys():
            # now values in the vrbos and abbs dicts get filled with an array of bedrooms,bathrooms,pax, lat/lng
            if len(vrbos): 
                # find the whole url from this property ID
                for l in links:
                    if ("vrbo.com" in l or "homeawa" in l)and vrbomatch in l:
                        if getvrbopage(l,prop): gotvrbo = 1

                        break
                # here, if no matches with vrbo.com try for any other vrbo
            
            
        for airbnbmatch in abbs.keys():
            # find the whole url from this property ID
            for l in links:
                if "airbnb.com" in l and airbnbmatch in l:
                    if getabbpage(l,prop): gotabb = 1
                    
                    break
        
    else:

        # throw away the links if it appears to have been a wrong property
        if not imgcount: links = []
        else:
            newlinks = []
            for i,l in enumerate(links):  # throw away links up to the first empty one
                if not l and len(links) > i+1: newlinks = links[i+1:]
    
        return 0
    gotvrbo = gotabb = 0
    if len(prop.vrbo_match): gotvrbo =1 
    if len(prop.abb_match): gotabb = 1
    return gotvrbo + gotabb   # max value = 2

def getvrbopage(url, prop):
    # gets the page, looks at key data and if matching the data in prop, it adds it into the Prop object
    if prop.vrbo_match == url: return
    
    referer = 'http://www.google.com/imghp'

    print ("fetching VRBO page:",url)
    result_html = fire_request(url, referer)
    page = to_ascii(result_html)
    lat = findbetween(page,'location":{"lat":',',')
    if not lat: lat = findbetween(page,'"lat":',',')
    if not lat: lat = findbetween(page,'homeaway:location:latitude" content="','"')
    if not lat: lat = findbetween(page,'"latitude":',',')
    lng = findbetween(page,',"lng":','}')
    if not lng: lng = findbetween(page,',"lng":',',')
    if not lng: lng = findbetween(page,'"homeaway:location:longitude" content="','"')
    if not lng: lng = findbetween(page,'"longitude":',',')
    beds= safeint(findbetween(page,',"bedrooms":',','))
    baths= safeint(findbetween(page,'"bathrooms":{"full":',','))
    pax = safeint(findbetween(page,',"sleeps":',','))

    # see how they differ and if OK, they are linked.
    print "calling link:",beds,baths,pax,lat,lng
    
    prop.link("vrbo",url,beds,baths,pax,lat,lng)
    
def getabbpage(url, prop):
    # gets the page, looks at key data and if matching the data in prop, it adds it into the Prop object
    if prop.abb_match == url: return
    if "wishlist" in url: return
    referer = 'http://www.google.com/imghp'

    print ("fetching airbnb page:",url)
    result_html = fire_request(url, referer)
    page = to_ascii(result_html)
    lat = findbetween(page,'"listing_lat":',',')
    lng = findbetween(page,',"listing_lng":',',')
    beds= safeint(findbetween(page,'"bedroom_label":"', ' '))
    baths= safeint(findbetween(page,'"bathroom_label":"',' '))
    pax = safeint(findbetween(page,'"guest_label":"',' '))
    if not lat or not lng: return
    
    # see how they differ and if OK, they are linked.
    prop.link("airbnb",url,beds,baths,pax,lat,lng)

def update_sheet( prop, allocated ):

    #print "Update_sheet for ", prop.id, prop.vrbo_match, prop.abb_match
    asheet = sheets.worksheet("active")
    if prop.vrbo_match:
        asheet.update_acell('I' + str(allocated), prop.vrbo_match)
        asheet.update_acell('J' + str(allocated), prop.vrbo_score)

    if prop.abb_match:
        asheet.update_acell('K' + str(allocated), prop.abb_match)
        asheet.update_acell('L' + str(allocated), prop.abb_score)


def alldigits(s):
    return ''.join(i for i in s if i.isdigit())

    
class listing:
    def __init__(self, id, images, beds, baths, pax, lat, lng):
        self.id = id
        self.images = images
        self.beds = beds
        self.baths = baths
        self.pax = pax
        self.lat = lat
        self.lng = lng
    
        self.abb_match = ""
        self.abb_score = 99
        self.vrbo_match = ""
        self.vrbo_score = 99
        
        
        #print "Got listing",id,"lat=",lat,"lng=",lng, "beds=",beds, "baths=",baths,"pax=",pax, "images=",len(images)
        #print images[0]
        #print images[1]
    def add_text(self,text):
        self.snippet = text.replace("\n"," ")

    def set_scores(self, autoa,autoa_score,autob,autob_score):
        self.vrbo_match = autoa
        self.vrbo_score = autoa_score
        self.abb_match = autob
        self.abb_score = autob_score
    

    def get_text(self):
        return self.snippet
    def link(self,site,url,beds,baths,pax,lat,lng):
    
        # Check that it's really a match. 
        dbeds = abs(beds-self.beds)
        dbaths = abs(baths-self.baths)
        if not baths or not self.baths: dbaths = 0  # sometimes the bathrooms count is missing
        dpax = abs(pax-self.pax)
        print "dev: lat ",lat," lng:",lng
        if not lat or not lng: return  # prevents trouble if it's not a property page (e.g. page diverted to a region page)
        dlat = abs(float(lat)-float(self.lat))
        dlng = abs(float(lng)-float(self.lng))
        print "lats:",lat, self.lat,"lngs:",lng, self.lng
        print "beds, baths, pax:", beds, self.beds , " | ", baths, self.baths," | ",pax,self.pax
        deviance = dbeds * 1.0 + dbaths *0.5 + dpax * 2 + dlat * 100 + dlng * 100
        
        print site,"matching. Deviance score:",deviance
        if deviance < 6.0:
            if "vrbo" in site:
                if deviance < self.vrbo_score:   # don't overwrite a good match with a worse one
                    self.vrbo_match = url
                    self.vrbo_score = deviance
            if "air" in site:
                if deviance < self.abb_score:
                    self.abb_match = url
                    self.abb_score = deviance
        
        
def do_hc_link(link):
    referer = 'http://www.google.com/imghp'

    print ("fetching:",link)
    result_html = fire_request(link, referer)

    page = to_ascii(result_html)
    id = link.split('/')[-1]
    imgrange = findbetween(page,"ImageObject",'"owner":')
    images = findbetween(imgrange,'href="','"',multi=True)
    # images now contains duplicate references for different sizes of image. Use even-numbered only:
    images = images[::2]  # or [1::2] for the odd numbered

    beds= safeint( findbetween(page, '"bedrooms":',',' ))
    baths = safeint( findbetween(page, '"bathrooms":',',' ))
    pax = safeint( findbetween(page, '"maxGuests":',',' ))
    lat = findbetween(page,'"lat":',',')
    lng = findbetween(page,'"lng":',',')
    text = findbetween(page,'<h1 class="index__title__Ohh65">','<') + "|"
    text += findbetween(page,'"summary":"','"') + "|"
    text += findbetween(page,'"description":"','"')
    print link.split("/")[-1],beds,baths,pax,lat,lng,len(images)
    
    result =  listing(id, images, beds, baths, pax, lat, lng)
    
    result.add_text( text )
    return result
    
def get_access():
    global credentials
    
    CLIENT_ID = '388474423779-tk17r66mbavu2t243707qnrtn7f47oeg.apps.googleusercontent.com'
    CLIENT_SECRET = 'bkLZKbDudeNwvZ-CGY5fUnmc'

    flow = OAuth2WebServerFlow(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scope='https://spreadsheets.google.com/feeds https://docs.google.com/feeds',
        redirect_uri='urn:ietf:wg:oauth:2.0:oob',
        access_type='offline',  # This is the default
        prompt='consent'
    )

    storage = Storage('creds.data')
    flags = argparser.parse_args(args=[])
    credentials = run_flow(flow, storage, flags)
    return credentials

    
def sheets_init():
    global sheets, credentials

    if not credentials:
        get_access()

    file = gspread.authorize(credentials)  # authenticate with Google
    sheets = file.open_by_key(G_SHEET)  # open sheet

    return

def fire_request(url, referer, proxy=""):

    headers = {
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Encoding': 'gzip,deflate',
        'Accept-Language': 'en-US,en;q=0.8,zh-TW;q=0.6,zh;q=0.4',
        'Cache-Control': 'no-cache',
        'Connection': 'close',
        'DNT': '1',
        'Pragma': 'no-cache',
        'Referer': referer,
        'User-Agent': random.choice(USER_AGENTS),
    }

    #print("Getting: ",url)
    
    try:
        r = requests.get(url, headers=headers,timeout=9)
    except:
        print(".",)
        r = requests.get(url, headers=headers,timeout=9)

    content = r.content.decode("utf-8")
    

    return content

def ohshitcaptcha():
    print "Google sent us a Captcha. I will pause 30 minutes. Alternatively, you could change IP address and re-start the program."
    time.sleep(60*30)
    





def search_by(image_url,hcid, imgno):

    result_url = GOOGLE_SEARCH_BY_ENDPOINT + image_url
    referer = 'http://www.google.com/imghp'
    result_html = fire_request(result_url, referer)
    with open("temp_"+hcid+"_"+str(imgno)+".html","wb") as output:  # debug/monitoring output files
        output.write(to_ascii(result_html))
    return result_html
    
def findbetween(page,tag1,tag2,after=None,multi=False):

    results = []
    start = 0
    if after:
        start = page.find(after)
    if start < 0: start = 0
    while 1:
        starting = page.find(tag1,start)
        if starting < 0: 
           if multi: return results
           else: return ""
        l1 = len(tag1)
        ending = page.find(tag2,starting + l1)
        if ending < 0:
            if multi: return results
            return ""
        result = page[starting+l1:ending]
        if not multi: return str(result)
        start = ending
        results.append(result)

def to_ascii(s):  # bad but quick way around character set problems
    s = s.encode('ascii',errors='ignore')
    return s
    
def safeint(s):
    try:
        return int(float(s))
    except:
        return 0

if __name__ == "__main__": main()