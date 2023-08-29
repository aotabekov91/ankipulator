import os
import json
import enum
import base64
import hashlib
import anki.sync
import urllib.request

from plug import Plug
from anki.storage import Collection

class MediaType(enum.Enum):

    Audio = 1
    Video = 2
    Picture = 3


class Submitter(Plug):

    def setSettings(self):

        super().setSettings()
        self.collection_path=os.path.expanduser(self.collection_path)

    def isNoteDuplicateOrEmptyInScope(

        self,
        note,
        deck,
        collection,
        duplicateScope,
        duplicateScopeDeckName,
        duplicateScopeCheckChildren,
        duplicateScopeCheckAllModels
    ):
        if duplicateScope != 'deck' and not duplicateScopeCheckAllModels:
            return note.dupeOrEmpty() or 0

        # Primary field for uniqueness
        val = note.fields[0]
        if not val.strip():
            return 1
        csum = anki.utils.fieldChecksum(val)

        # Create dictionary of deck ids
        dids = None
        if duplicateScope == 'deck':
            did = deck['id']
            if duplicateScopeDeckName is not None:
                deck2 = collection.decks.byName(duplicateScopeDeckName)
                if deck2 is None:
                    # Invalid deck, so cannot be duplicate
                    return 0
                did = deck2['id']

            dids = {did: True}
            if duplicateScopeCheckChildren:
                for kv in collection.decks.children(did):
                    dids[kv[1]] = True

        # Build query
        query = 'select id from notes where csum=?'
        queryArgs = [csum]
        if note.id:
            query += ' and id!=?'
            queryArgs.append(note.id)
        if not duplicateScopeCheckAllModels:
            query += ' and mid=?'
            queryArgs.append(note.mid)

        # Search
        for noteId in collection.db.list(query, *queryArgs):
            if dids is None:
                # Duplicate note exists in the collection
                return 2
            # Validate that a card exists in one of the specified decks
            for cardDeckId in collection.db.list('select did from cards where nid=?', noteId):
                if cardDeckId in dids:
                    return 2

        # Not a duplicate
        return 0

    def storeMediaFile(self, 
                       filename, 
                       data=None, 
                       url=None, 
                       skipHash=None, 
                       deleteExisting=True):

        if not (data or url):
            raise Exception('You must provide a "data", "path", or "url" field.')
        if data:
            mediaData = base64.b64decode(data)
        elif url:
            mediaData = self.download(url)

        if skipHash is None:
            skip = False
        else:
            m = hashlib.md5()
            m.update(mediaData)
            skip = skipHash == m.hexdigest()

        if skip:
            return None
        if deleteExisting:
            self.deleteMediaFile(filename)


        collection=Collection(self.collection_path)
        media=collection.media
        r=media.writeData(filename, mediaData)
        collection.autosave()
        return r

    def deleteMediaFile(self, filename):

        collection=Collection(self.collection_path)
        media = collection.media
        try:
            media.syncDelete(filename)
        except AttributeError:
            media.trash_files([filename])
        collection.autosave()

    def addNote(self, note):

        collection=Collection(self.collection_path) 
        model = collection.models.byName(note['modelName'])
        deck = collection.decks.byName(note['deckName'])
        collection.decks.set_current(deck['id'])
        collection.models.set_current(model)
        ankiNote = collection.newNote()
        ankiNote.model()['did'] = deck['id']

        if 'tags' in note:
            ankiNote.tags = note['tags']

        for name, value in note['fields'].items():
            for ankiName in ankiNote.keys():
                if name.lower() == ankiName.lower():
                    ankiNote[ankiName] = value
                    break

        self.addMediaFromNote(ankiNote, note)

        allowDuplicate = False
        duplicateScope = None
        duplicateScopeDeckName = None
        duplicateScopeCheckChildren = False
        duplicateScopeCheckAllModels = False

        duplicateOrEmpty = self.isNoteDuplicateOrEmptyInScope(
            ankiNote,
            deck,
            collection,
            duplicateScope,
            duplicateScopeDeckName,
            duplicateScopeCheckChildren,
            duplicateScopeCheckAllModels
        )

        if duplicateOrEmpty == 1:
            raise Exception('cannot create note because it is empty')
        elif duplicateOrEmpty == 2:
            if not allowDuplicate:
                raise Exception('cannot create note because it is a duplicate')

        nCardsAdded = collection.addNote(ankiNote)
        if nCardsAdded < 1:
            raise Exception('The field values you have provided would make an empty question on all cards.')

        collection.autosave()
        collection.close()
        return ankiNote.id

    def addMediaFromNote(self, ankiNote, note):

        audioObjectOrList = note.get('audio')
        self.addMedia(ankiNote, audioObjectOrList, MediaType.Audio)

        videoObjectOrList = note.get('video')
        self.addMedia(ankiNote, videoObjectOrList, MediaType.Video)

        pictureObjectOrList = note.get('picture')
        self.addMedia(ankiNote, pictureObjectOrList, MediaType.Picture)

    def addMedia(self, ankiNote, mediaObjectOrList, mediaType):

        if mediaObjectOrList is None:
            return

        if isinstance(mediaObjectOrList, list):
            mediaList = mediaObjectOrList
        else:
            mediaList = [mediaObjectOrList]

        for media in mediaList:
            if media is not None and len(media['fields']) > 0:
                try:
                    path=media.get('path')
                    if path:
                        mediaFilename=media['filename']
                    else:
                        mediaFilename = self.storeMediaFile(media['filename'],
                                                        data=media.get('data'),
                                                        url=media.get('url'),
                                                        skipHash=media.get('skipHash'),
                                                        deleteExisting=media.get('deleteExisting'))

                    if mediaFilename is not None:
                        for field in media['fields']:
                            if field in ankiNote:
                                if mediaType is MediaType.Picture:
                                    ankiNote[field] += u'<img src="{}">'.format(mediaFilename)
                                elif mediaType is MediaType.Audio or mediaType is MediaType.Video:
                                    ankiNote[field] += u'[sound:{}]'.format(mediaFilename)

                except Exception as e:
                    errorMessage = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    for field in media['fields']:
                        if field in ankiNote:
                            ankiNote[field] += errorMessage

    def addNotes(self, notes):

        if type(notes)!=list: notes=[notes]

        try:
            results=self.invoke('addNotes', notes=notes)
        except: 
            results = []
            for note in notes: results.append(self.addNote(note))
        return results

    def getModels(self):

        c=Collection(self.collection_path)
        models=c.models.all()
        data={}
        for m in models:
            flds=[f['name'] for f in m['flds']]
            data[m['name']]=flds
        c.close()
        return data

    def getDecks(self):

        c=Collection(self.collection_path)
        decks=c.decks.all_names_and_ids()
        c.close()
        return decks

    def request(self, action, **params):
            return {'action': action, 'params': params, 'version': 6}

    def invoke(self, action, **params):

        requestJson = json.dumps(
                self.request(action, **params)).encode('utf-8')
        response =json.load(urllib.request.urlopen(
                    urllib.request.Request('http://localhost:8765', requestJson)))

        if len(response) != 2:
            raise Exception('response has an unexpected number of fields')
        if 'error' not in response:
            raise Exception('response is missing required error field')
        if 'result' not in response:
            raise Exception('response is missing required result field')
        if response['error'] is not None:
            raise Exception(response['error'])
        return response['result']

    def download(self, url):

        client = anki.sync.AnkiRequestsClient()
        client.timeout = 2000

        resp = client.get(url)
        if resp.status_code != 200:
            e=Exception(
                    '{} download failed with return code {}'.format(
                        url, resp.status_code))
            raise e
        return client.streamContent(resp)
