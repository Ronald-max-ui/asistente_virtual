"""Incremental spoken sentences; preserve decimals, initials and abbreviations."""
import re
ABBREVIATIONS={'sr','sra','srta','dr','dra','lic','ing','av','jr','etc','p','ej','s','no','nro'}
class SentenceSegmenter:
    def __init__(self):self.buffer=''
    def feed(self,text):
        self.buffer+=text;segments=[];start=0
        for match in re.finditer(r'[.!?](?:["”»])?\s+',self.buffer):
            stop=match.start();punct=self.buffer[stop]
            token=re.search(r'([\w]+)$',self.buffer[:stop])
            if punct=='.' and token:
                value=token.group(1).lower()
                if value in ABBREVIATIONS or (len(value)==1 and value.isalpha()):continue
                if value.isdigit() and not self.buffer[start:stop].strip().replace(value,'',1).strip():continue
            segments.append(self.buffer[start:match.end()].rstrip());start=match.end()
        self.buffer=self.buffer[start:]
        return segments
    def finish(self):
        text=self.buffer;self.buffer='';return text
