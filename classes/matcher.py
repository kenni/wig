import re

class Match(object):
	def __init__(self):
		self.error_pages = set()	
	
	def _check_page(self, response, fingerprint):

		# check if the page is a 404
		is_404 = response.status['code'] == 404 or response.md5_404 in self.error_pages

		# fingerprints that do not have a 'code' set, default to 200
		# find the 'code' of the current fingerprint
		fp_code = 200 if not 'code' in fingerprint else fingerprint['code']

		if fp_code == 'any':
			return True

		# if the fingerprint is for a 404 but the page is not a 404, do not match
		elif (not is_404) and fp_code == 404:
			return False

		# if the page is a 404 but the fingerprint is not for a 404, do not match
		elif is_404 and (not fp_code == 404):
			return False

		# else match
		else:
			return True


	def set_404s(self, set_of_404s):
		self.error_pages = set_of_404s


	def get_result(self, fingerprints, response):
		# find the matching method to use
		matches = []

		# find out of the reponse is an image
		# this is used to avoid the crawler using string and regex
		# searching for matches in these files
		content_type = 'Content-Type'.lower()
		if content_type in response.headers:
			is_image = 'image' in response.headers[content_type]

		# default to the content being an image, since if the content-type
		# isn't set, the content is unknown
		else:
			is_image = True

		for fingerprint in fingerprints:

			# only check the page if the status codes match
			if not self._check_page(response, fingerprint):
				matches.append(None)

			elif 'type' not in fingerprint:
				matches.append(None)

			elif fingerprint['type'] == 'md5':
				matches.append(self.md5(fingerprint, response))
			
			elif fingerprint['type'] == 'string' and not is_image:
				matches.append(self.string(fingerprint, response))
			
			elif fingerprint['type'] == 'regex' and not is_image:
				matches.append(self.regex(fingerprint, response))

			elif fingerprint['type'] == 'header':
				matches.append(self.header(fingerprint, response))

			else:
				# fingerprint type is not supported yet
				matches.append(None)

		matches = [fp for fp in matches if fp is not None]

		return matches

	
	def md5(self, fingerprint, response):
		if fingerprint["md5"] == response.md5:
			return fingerprint
		else:
			return None

	
	def string(self, fingerprint, response):
		if fingerprint["string"] in response.body:
			return fingerprint
		else:
			return None

	
	def regex(self, fingerprint, response):
		# create copy of fingerprint
		copy = {key:fingerprint[key] for key in fingerprint}

		regex = copy["regex"]
		output = copy["output"]

		matches = re.findall(regex, response.body)
		if len(matches):
			if "%" in output:
				copy['output'] = output % matches[0]
			
			return copy
		else:
			return None

	
	def header(self, fingerprint, response):
		fp_header = fingerprint['header']
		match_type = 'string' if 'string' in fingerprint else 'regex'

		# a dummy class to mimic a response
		class response_dummy(object):
			self.body = ''

		# parse the headers searching for a match
		for header in response.headers:
			if header == fp_header.lower():

				# create an intance of the dummy class
				r = response_dummy()
				r.body = response.headers[header]

				# call the Match instances methods for string or regex matching
				if 'string' in fingerprint:
					return self.string(fingerprint, r)
				else:
					return self.regex(fingerprint, r)




