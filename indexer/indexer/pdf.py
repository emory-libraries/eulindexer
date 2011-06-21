# file eulindexer/pdf.py
# 
#   Copyright 2010,2011 Emory University Libraries
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

# not sure where this code should ultimately belong...
# putting it here until we decide

from pyPdf import PdfFileReader

def pdf_to_text(pdfstream):
    '''Extract the text from a PDF document, e.g. to add PDF text
    content to an index for searching.

    :param pdfstream: A file-like object that supports read and seek
	    methods, as required by :class:`pyPdf.PdfFileReader` 

    '''
    pdfreader = PdfFileReader(pdfstream)
    if pdfreader.isEncrypted:
        raise Exception('Cannot extract text from encrypted PDF documents')
    return '\n'.join([page.extractText() for page in pdfreader.pages])

    
