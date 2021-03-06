import re, hashlib, pprint, socket, urllib
from collections import Counter
from html.parser import HTMLParser
from classes.fingerprints import Fingerprints
#from classes.requester2 import Requester
from classes.matcher import Match
from classes.request2 import Response, Requester
from classes.printer import Printer


class DiscoverIP(object):

	def __init__(self, path):
		self.path = path

	def run(self):
		try:
			hostname = self.path.split('//')[1]
			hostname = hostname.split('/')[0]
			ip = socket.gethostbyname(hostname)
		except Exception as e:
			#print(e)
			ip = 'Unknown'

		return ip


class DiscoverTitle(object):

	def __init__(self, options, data):
		self.data = data
		self.url = options['url']

	def run(self):
		self.data['requester'].set_fingerprints([ [{'host': self.url, 'url': '/', }] ])
		r = self.data['requester'].run()

		front_page = self.data['cache'][self.url]

		try:
			title = re.findall('<title>\s*(.*)\s*</title>', front_page.body)[0]
			title = title.strip()
		except:
			title = ''

		return title


class DiscoverCookies(object):

	def __init__(self, data):
		self.data = data

	def run(self):
		cookies = set()
		for r in self.data['cache'].get_responses():
			try:
				c = r.headers['set-cookie']
				cookies.add(c.strip().split('=')[0])
			except:
				pass

		return cookies



class DiscoverErrorPage:
	# find error pages on the site
	# the requester has a built-in list of items and patterns
	# to remove before calculating a checksum of pages that
	# should not exists

	def __init__(self, options, data):
		self.host = options['url']
		self.urls = data['fingerprints'].get_error_urls()
		self.requester = data['requester']
		self.printer = data['printer']


	def run(self):
		self.printer.print('Error page detection...', 1)

		urls = [ [{'host': self.host, 'url': u}] for u in self.urls ]

		self.requester.set_fingerprints(urls)
		self.requester.set_find_404(True)
		results = self.requester.run()

		error_pages = set()
		while results.qsize() > 0:
			md5sum, url = results.get()
			error_pages.add(md5sum)
			self.printer.print('- Error page fingerprint: %s - %s' % (md5sum, url), 3)

		self.requester.set_find_404(False)

		return error_pages
		


class DiscoverCMS(object):

	def __init__(self, options, data):
		self.chunk_size = options['chunk_size']
		self.printer = data['printer']
		self.matcher = data['matcher']
		self.requester = data['requester']
		self.fps = data['fingerprints'].get_ordered_list()
		self.fps_iter = iter(self.fps)
		self.index = 0
		

	def is_done(self):
		return self.index >= len(self.fps)


	def run(self):
		i = self.index
		cs = self.chunk_size

		# extract a chunck
		chunk = self.fps[i:i+cs]
		self.index += cs

		self.requester.set_fingerprints(chunk)
		results = self.requester.run()

		# process the results and find matches
		while results.qsize() > 0:
			fps,response = results.get()
			matches = self.matcher.get_result(fps, response)
			if matches:
				return [cms['cms'] for cms in matches]

		return []


class DiscoverVersion(object):
	def __init__(self, options, data):
		self.chunk_size = options['chunk_size']
		self.printer = data['printer']
		self.result = data['results']
		self.matcher = data['matcher']
		self.requester = data['requester']
		self.fingerprints = data['fingerprints']


	def run(self, cms):
		self.printer.print('Version detection...', 1)
		cs = self.chunk_size
		fps = self.fingerprints.get_fingerprints_for_cms(cms)

		for i in range(0, len(fps), cs):
			chunk = fps[i:i+cs]

			self.requester.set_fingerprints(chunk)
			results = self.requester.run()

			while results.qsize() > 0:
				res_fps,response = results.get()
				for fp in self.matcher.get_result(res_fps, response):

					self.result.add( fp['category'], fp['cms'], fp['output'], fp)


class DiscoverOS(object):
	def __init__(self, options, data):
		self.printer = data['printer']
		self.cache = data['cache']
		self.results = data['results']
		self.fingerprints = data['fingerprints'].get_os_fingerprints()

		self.category = "Operating System"
		self.os = Counter()
		self.packages = Counter()
		self.oss = []
		self.matched_packages = set()


	def find_match(self, response):
		headers = response.headers
		if 'server' in headers:
			line = headers['server']
			
			if "(" in line:
				os = line[line.find('(')+1:line.find(')')]
				line = line[:line.find('(')-1] + line[line.find(')')+1: ]
			else:
				os = False

			if os:
				self.oss.append(os.lower())
				self.printer.print('- OS Family: %s' % (os, ), 4)

			for part in line.split(" "):
				try:
					pkg,version = list(map(str.lower, part.split('/')))
					self.packages[pkg] += 1

					os_list = self.fingerprints[pkg][version]

					for i in os_list:
						if len(i) == 2:
							os, os_version = i
							weight = 1
						elif len(i) == 3:
							os, os_version, weight = i

						self.matched_packages.add( (os, os_version, pkg, version) )
						self.os[(os, os_version)] += weight

				except Exception as e:
					continue


	def finalize(self):
		
		platforms = self.results.get_platform_results()
		for pkg in platforms:
			for version in platforms[pkg]:
				# hack for asp.net
				if pkg == 'ASP.NET':
					version = version[:3] if not version.startswith("4.5") else version[:5]

				try:
					for i in self.fingerprints[pkg.lower()][version]:
						if len(i) == 2:
							os, os_version = i
							weight = 1
						elif len(i) == 3:
							os, os_version, weight = i

						self.matched_packages.add( (os, os_version, pkg, version) )
						self.os[(os, os_version)] += platforms[pkg][version]*weight

				except Exception as e:
					pass

		# if an os string 'self.oss' has been found in the header
		# prioritize the identified os's in self.os
		# iterate over the list of os strings found
		for os in self.oss:
			# iterate over the fingerprinted os's
			for key in self.os:
				if os in key[0].lower():
					self.printer.print('- Prioritizing fingerprints for OS: %s' % (key, ), 4)
					self.os[key] += 100

		# add OS to results: self.os: {(os, version): weight, ...}
		results = []
		for p in self.os:
			results.append({'version': p[1], 'os': p[0], 'count': self.os[p]})

		if len(results) == 0: return

		prio = sorted(results, key=lambda x:x['count'], reverse=True)
		max_count = prio[0]['count']
		for i in prio:
			if i['count'] == max_count:
				self.results.add(self.category, i['os'], i['version'], weight=i['count'])
			else:
				break


	def run(self):
		self.printer.print('OS detection...', 1)
		headers = set()
		responses = self.cache.get_responses()
		for response in responses:
			self.find_match(response)

		self.finalize()



# Used by the DiscoverMore crawler
# The
class LinkExtractor(HTMLParser):
	def __init__(self, strict):
		super().__init__(strict=strict)
		self.results = set()

	def get_results(self):
		return self.results

	def handle_starttag(self, tag, attrs):
		try:
			url = ''
			if tag == 'script' or tag == 'img':
				for attr in attrs: 
					if attr[0] == 'src':  self.results.add(attr[1])
			if tag == 'link':
				for attr in attrs: 
					if attr[0] == 'href': self.results.add(attr[1])
		except:
			pass



class DiscoverMore(object):

	def __init__(self, options, data):
		self.host = options['url']
		self.threads = options['threads']
		self.printer = data['printer']
		self.cache = data['cache']
		self.result = data['results']
		self.matcher = data['matcher']
		self.requester = data['requester']
		self.fingerprints = data['fingerprints']


	def _get_urls(self, response):
		# only get urls from elements that use 'src' to avoid 
		# fetching resources provided by <a>-tags, as this could
		# lead to the crawling of the whole application
		regexes = [ 'src="(.+?)"', "src='(.+?)'"]

		urls = set()
		for regex in regexes:
			for match in re.findall(regex, response.body):
				urls.add( match )

		return urls

	
	def run(self):
		self.printer.print('Link extraction...', 1, '')
		resources = set()
		parser = LinkExtractor(strict=False)

		for req in self.cache.get_responses():
			# skip pages that do not set 'content-type'
			# these might be binaries
			if not 'content-type' in req.headers:
				continue

			# only scrape pages that can contain links/references
			if 'text/html' in req.headers['content-type']:
				tmp = self._get_urls(req)

				parser.feed(req.body)
				tmp = tmp.union( parser.get_results())

				for i in tmp:
					
					# ensure that only resources located on the domain /sub-domain is requested 
					if i.startswith('http') or i.startswith('//'):
						try:
							parts = i.split('/')
							host = parts[2]
						except:
							continue

						# if the resource is out side of the domain, skip it
						if not host in self.host.split('/')[2]:
							continue

						# else update the url so that it only contains the relative location
						else:
							i = '/' + '/'.join(parts[3:])

					resources.add( i )

		# the items in the resource set should mimic a list of fingerprints:
		# a fingerprint is a dict with at least an URL key
		urls = [ [{'url':i}] for i in resources ]
		self.printer.print(' Discovered %s new resources' % (len(urls), ), 2, '')

		# fetch the discovered resources.
		# As this class' purpose only is to fetch the resource (add to cache)
		# there is no return value, or further actions needed
		for i in range(0, len(urls), self.threads):
			self.requester.set_fingerprints( urls[i:i+self.threads] )
			results = self.requester.run()

		self.printer.print('', 1)



class DiscoverAllCMS(object):
	# match all fingerprints against all responses
	# this might generate false positives

	def __init__(self, data):
		self.cache = data['cache']
		self.fps = data['fingerprints'].get_all()
		self.results = data['results']
		self.matcher = data['matcher']


	def run(self):
		# find matches for all the responses in the cache
		for response in self.cache.get_responses():
			matches = self.matcher.get_result(self.fps, response)
			for fp in matches:
				self.results.add_cms(fp)
	

class DiscoverJavaScript(object):
	def __init__(self, options, data):
		self.printer = data['printer']
		self.cache = data['cache']
		self.fingerprints = data['fingerprints'].get_js_fingerprints()
		self.matcher = data['matcher']
		self.result = data['results']

	def run(self):
		self.printer.print('Javascript detection...', 1)
		for response in self.cache.get_responses():
			
			# match only if the response is JavaScript
			#  check content type
			content_type = response.headers['content-type'] if 'content-type' in response.headers else ''
			# and extension
			is_js = 'javascript' in content_type or '.js' in response.url.split('.')[-1]

			# if the response is JavaScript try to match it to the known fingerprints 
			if is_js:
				matches = self.matcher.get_result(self.fingerprints, response)
				for fp in matches:
					self.result.add( fp['category'], fp['name'], fp['output'], fingerprint=fp, weight=1)


class DiscoverInteresting(object):
	def __init__(self, options, data):
		self.printer = data['printer']
		self.requester = data['requester']
		self.interesting = data['fingerprints'].get_interesting_fingerprints()
		self.matcher = data['matcher']
		self.result = data['results']
		self.threads = options['threads']
		self.category = "Interesting"

	def run(self):
		self.printer.print('Detecting interesting files...', 1)

		cs = self.threads

		for i in range(0, len(self.interesting), cs):
			chunk = self.interesting[i:i+cs]

			self.requester.set_fingerprints(chunk)
			results = self.requester.run()
			while results.qsize() > 0:
				fps,response = results.get()
				for fp in self.matcher.get_result(fps, response):
					self.result.add( self.category, None, None, fp, weight=1)


class DiscoverUrlLess(object):
	def __init__(self, options, data):
		self.printer = data['printer']
		self.cache = data['cache']
		self.fps = data['fingerprints'].get_url_less()
		self.results = data['results']
		self.matcher = data['matcher']

	def run(self):
		self.printer.print('Matching urlless fingerprints...', 1)
		
		# find matches for all the responses in the cache
		for response in self.cache.get_responses():
			matches = self.matcher.get_result(self.fps, response)
			for fp in matches:
				if 'name' in fp:	name = fp['name']
				elif 'cms' in fp:	name = fp['cms']
				else:				name = ''

				self.results.add(fp['category'], name, fp['output'], fingerprint=fp, weight=1)


class DiscoverVulnerabilities:
	def __init__(self, data):
		self.results = data['results']
		self.fps = data['fingerprints']

	def run(self):
		self.results.update()
		cms_results = self.results.get_versions()

		vendors = Counter()
		for r in cms_results: vendors[r[0]] += 1

		# if there are more than 5 results,
		# skip displaying vuln count, as the 
		# results are unreliable
		for cms, version in cms_results:
			if vendors[cms] > 5: continue

			try:
				vulns = self.fps.vulnerabilities[cms][version]
				num_vulns = vulns['num_vulns']
				link = vulns['version_id']
				self.results.add_vulnerabilities(cms, version, num_vulns, link)
			except Exception as e:
				pass


class DiscoverTools:
	def __init__(self, data):
		self.fps = data['fingerprints']
		self.results = data['results']

	def run(self):
		self.results.update()
		cms_results = self.results.get_versions()

		# loop over the cms' in the results
		for cms,_ in cms_results:
			# loop over all the translations
			for fn in self.fps.translator:
				# check if the translated name is the same as the cms
				if self.fps.translator[fn]['name'] == cms and 'tool' in self.fps.translator[fn]:
					for tool in self.fps.translator[fn]['tool']:
						self.results.add_tool(cms, tool['name'], tool['link'])

		

