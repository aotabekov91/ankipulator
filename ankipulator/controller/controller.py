import zmq
import threading
# import the main window object (mw) from aqt
from aqt import mw
# import the "show info" tool from utils.py
from aqt.utils import showInfo, qconnect
# import all of the Qt GUI library
from aqt.qt import *

# We're going to add a menu item below. First we want to create a function to
# be called when the menu item is activated.

def testFunction() -> None:
    # get the number of cards in the current collection, which is stored in
    # the main window
    cardCount = mw.col.cardCount()
    # show a message box
    showInfo("Card count: %d" % cardCount)

class AnkiServer:

    def __init__(self):
        self.port=19898
        self.running=False
        self.set_connection()

    def set_connection(self):
        self.socket=zmq.Context().socket(zmq.REP)
        self.socket.bind(f'tcp://*:{self.port}')

    def respond(self, request):

        # try:

        if request['command']=='getAllDecks':
            decks=mw.col.db.list('select * from decks')
            msg={'decks':decks}
        elif request['command']=='exit':
            self.running=False
        elif request['command']=='reviewerState':
            msg={'reviewer_state':mw.reviewer.state}
            # answer question transition or none
        elif request['command']=='currentCardData':
            card=mw.reviewer.card
            if card:
                note=card.note()
                data={'mid':note.mid,
                     'mname':mw.col.models.get(note.mid)['name'],
                     'field_values':{},
                      'nid':note.id,
                     'card_type': card.template()['name'],
                     }
                for f, j  in note.items():
                    data['field_values'][f]=j
                msg={'data':data}
            else:
                msg={'word':'none'}
        elif request['command']=='updateNote':
            data=request.get('data', None)
            nid=request.get('nid', None)
            card=mw.reviewer.card
            note=card.note()
            if data and nid==note.id:
                for f, v in data.items():
                    note[f]=v
                mw.col.update_note(note)
            msg={'status':'ok', 'info': 'updated note'}
        elif request['command']=='refreshReviewer':
            mw.col.reset()
            mw.col.autosave()
            mw.reviewer._redraw_current_card()
            mw.fade_in_webview()
            mw.maybeReset()
            mw.requireReset()
            mw.progress.finish()
            mw.reset()
            msg={'status':'ok', 'info': 'refreshing'}
        else:
            msg={'status':'nok', 'info': 'not understood'}

        # except:
        #     err_type, error, traceback = sys.exc_info()
        #     msg={'status':'nok', 'info':'{err}'.format(err=error)}

        self.socket.send_json(msg)

    def run(self):
        def start():
            self.running=True
            while self.running:
                request=self.socket.recv_json()
                self.respond(request)
        t=threading.Thread(target=start)
        t.daemon=True
        t.start()

svr=AnkiServer()
svr.run()
