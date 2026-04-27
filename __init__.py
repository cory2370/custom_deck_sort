import re
import random
from collections import defaultdict
from aqt import mw
from aqt.qt import *
from aqt.deckbrowser import DeckBrowser

ZWSP_0 = "\u200B"
ZWSP_1 = "\u200C"

def strip_zwsp(text):
    return text.replace(ZWSP_0, "").replace(ZWSP_1, "")

def generate_zwsp_prefix(index):
    # Expanded to 16 bits to safely support up to 65,536 decks
    binary_str = format(index, '016b')
    return binary_str.replace('0', ZWSP_0).replace('1', ZWSP_1)

def get_zwsp_prefix(text):
    prefix_chars = []
    for c in text:
        if c in (ZWSP_0, ZWSP_1):
            prefix_chars.append(c)
        else:
            break
    return "".join(prefix_chars)

def auto_integrate_new_decks():
    if not mw or not mw.col:
        return False

    decks = mw.col.decks.all()
    unprefixed = []

    for deck in decks:
        base_name = deck['name'].split("::")[-1]
        if not get_zwsp_prefix(base_name):
            unprefixed.append(deck)

    if not unprefixed or len(unprefixed) == len(decks):
        return False

    siblings = defaultdict(list)

    for deck in decks:
        parts = deck['name'].split("::")
        parent = "::".join(parts[:-1])
        base_name = parts[-1]

        prefix = get_zwsp_prefix(base_name)

        if prefix:
            binary_str = prefix.replace(ZWSP_0, '0').replace(ZWSP_1, '1')
            val = int(binary_str, 2)
            is_prefixed = True
            clean_name = base_name[len(prefix):]
        else:
            val = 999999
            is_prefixed = False
            clean_name = base_name

        siblings[parent].append({
            'deck': deck,
            'val': val,
            'is_prefixed': is_prefixed,
            'clean_name': clean_name,
            'raw_name': deck['name']
        })

    def natural_sort_key(text):
        return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

    global_order = []

    def process_children(parent_path):
        if parent_path not in siblings:
            return

        group = siblings[parent_path]
        prefixed = [d for d in group if d['is_prefixed']]
        unprefixed = [d for d in group if not d['is_prefixed']]

        prefixed.sort(key=lambda x: x['val'])
        unprefixed.sort(key=lambda x: natural_sort_key(x['clean_name']))

        ordered = list(prefixed)
        for u_deck in unprefixed:
            u_key = natural_sort_key(u_deck['clean_name'])
            inserted = False
            for i, p_deck in enumerate(ordered):
                p_key = natural_sort_key(p_deck['clean_name'])
                if u_key < p_key:
                    ordered.insert(i, u_deck)
                    inserted = True
                    break
            if not inserted:
                ordered.append(u_deck)

        for item in ordered:
            global_order.append(item['deck'])
            process_children(item['raw_name'])

    process_children("")

    changed_any = False
    for idx, deck in enumerate(global_order):
        fresh_deck = mw.col.decks.get(deck['id'])
        if not fresh_deck: continue

        parts = fresh_deck['name'].split("::")
        base_name = parts[-1]
        clean_base_name = strip_zwsp(base_name)
        new_base_name = generate_zwsp_prefix(idx) + clean_base_name

        if base_name != new_base_name:
            parts[-1] = new_base_name
            new_full_name = "::".join(parts)
            mw.col.decks.rename(fresh_deck, new_full_name)
            changed_any = True

    if changed_any:
        mw.col.setMod()
    return changed_any

original_refresh = DeckBrowser.refresh

_is_sorting = False
def custom_refresh(self, *args, **kwargs):
    global _is_sorting
    if not _is_sorting:
        _is_sorting = True
        try:
            auto_integrate_new_decks()
        except Exception:
            pass
        finally:
            _is_sorting = False
    return original_refresh(self, *args, **kwargs)

DeckBrowser.refresh = custom_refresh

class DeckSorterDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Custom Deck Sorter")
        self.resize(450, 600)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        info_label = QLabel(
            "<b>Drag and drop the decks below to set your custom order!</b><br>"
            "<small style='color: gray;'>Note: Subdecks will automatically stay grouped under their parent decks. Alpaca children will be taken care of by their alpaca parents.</small>"
        )
        layout.addWidget(info_label)

        self.list_widget = QListWidget()
        self.list_widget.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list_widget.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list_widget.setAlternatingRowColors(True)
        self.list_widget.setStyleSheet("""
            QListWidget {
                border: 1px solid #aaa;
                border-radius: 4px;
                padding: 4px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #ccc;
            }
        """)
        layout.addWidget(self.list_widget)
        self.populate_list()

        sort_btn_layout = QHBoxLayout()

        self.btn_auto_sort = QPushButton("🔢 Auto-Sort Numerically")
        self.btn_auto_sort.setToolTip("Automatically orders all decks and subdecks strictly by their numbers.")
        self.btn_auto_sort.clicked.connect(self.auto_sort_numerically)
        sort_btn_layout.addWidget(self.btn_auto_sort)

        self.btn_sort_randomly = QPushButton("🔀 Shuffle Randomly")
        self.btn_sort_randomly.setToolTip("Shuffles siblings randomly while keeping them inside their correct parent decks.")
        self.btn_sort_randomly.clicked.connect(self.sort_randomly)
        sort_btn_layout.addWidget(self.btn_sort_randomly)

        self.btn_reset_sort = QPushButton("❌ Reset to Default")
        self.btn_reset_sort.setToolTip("Wipes all custom sorting and restores Anki's default alphabetical order.")
        self.btn_reset_sort.setStyleSheet("QPushButton { color: #d9534f; font-weight: bold; }")
        self.btn_reset_sort.clicked.connect(self.reset_sort)
        sort_btn_layout.addWidget(self.btn_reset_sort)

        layout.addLayout(sort_btn_layout)

        btn_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        btn_box.accepted.connect(self.save_order)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def populate_list(self):
        tree = mw.col.decks.deck_tree()

        def add_nodes(node, indent_level=0):
            if node.deck_id != 0:
                display_name = strip_zwsp(node.name.split("::")[-1])
                indent_str = "    " * indent_level
                if indent_level > 0:
                    indent_str += "└─ "
                item = QListWidgetItem(f"{indent_str}{display_name}")
                item.setData(Qt.ItemDataRole.UserRole, node.deck_id)
                self.list_widget.addItem(item)

            for child in node.children:
                add_nodes(child, indent_level + (1 if node.deck_id != 0 else 0))

        add_nodes(tree)

    def auto_sort_numerically(self):
        items = []
        while self.list_widget.count() > 0:
            items.append(self.list_widget.takeItem(0))

        tree = defaultdict(list)
        for item in items:
            did = item.data(Qt.ItemDataRole.UserRole)
            deck = mw.col.decks.get(did)
            if not deck: continue
            raw_name = deck['name']
            parts = raw_name.split("::")
            parent = "::".join(parts[:-1])

            node = {'item': item, 'base_name': strip_zwsp(parts[-1]), 'raw_name': raw_name}
            tree[parent].append(node)

        sorted_items = []

        def natural_sort_key(node):
            text = node['base_name']
            return [int(c) if c.isdigit() else c.lower() for c in re.split(r'(\d+)', text)]

        def add_children(parent_name):
            if parent_name in tree:
                children = tree[parent_name]
                children.sort(key=natural_sort_key)
                for child in children:
                    sorted_items.append(child['item'])
                    add_children(child['raw_name'])

        add_children("")

        for item in sorted_items:
            self.list_widget.addItem(item)

    def sort_randomly(self):
        items = []
        while self.list_widget.count() > 0:
            items.append(self.list_widget.takeItem(0))

        tree = defaultdict(list)
        for item in items:
            did = item.data(Qt.ItemDataRole.UserRole)
            deck = mw.col.decks.get(did)
            if not deck: continue
            raw_name = deck['name']
            parts = raw_name.split("::")
            parent = "::".join(parts[:-1])

            node = {'item': item, 'base_name': strip_zwsp(parts[-1]), 'raw_name': raw_name}
            tree[parent].append(node)

        shuffled_items = []
        def add_children(parent_name):
            if parent_name in tree:
                children = tree[parent_name]
                random.shuffle(children)
                for child in children:
                    shuffled_items.append(child['item'])
                    add_children(child['raw_name'])

        add_children("")

        for item in shuffled_items:
            self.list_widget.addItem(item)

    def reset_sort(self):
        reply = QMessageBox.question(
            self, 'Reset Custom Sort',
            'Are you sure you want to remove all custom sorting?\nThis will restore Anki\'s default alphabetical order.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.No:
            return

        mw.checkpoint("Reset Deck Sort")

        decks_to_rename = []
        for deck in mw.col.decks.all():
            if ZWSP_0 in deck['name'] or ZWSP_1 in deck['name']:
                decks_to_rename.append(deck['id'])

        def get_depth(did):
            deck = mw.col.decks.get(did)
            return deck['name'].count('::') if deck else 0

        decks_to_rename.sort(key=get_depth)

        for did in decks_to_rename:
            deck = mw.col.decks.get(did)
            if not deck: continue
            new_name = strip_zwsp(deck['name'])
            if new_name != deck['name']:
                mw.col.decks.rename(deck, new_name)

        mw.col.setMod()
        mw.deckBrowser.refresh()

        self.list_widget.clear()
        self.populate_list()

    def save_order(self):
        mw.checkpoint("Sort Decks")

        ordered_dids = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            ordered_dids.append(item.data(Qt.ItemDataRole.UserRole))

        for idx, did in enumerate(ordered_dids):
            deck = mw.col.decks.get(did)
            if not deck: continue
            parts = deck['name'].split("::")
            base_name = parts[-1]

            clean_base_name = strip_zwsp(base_name)
            new_base_name = generate_zwsp_prefix(idx) + clean_base_name

            if base_name != new_base_name:
                parts[-1] = new_base_name
                new_full_name = "::".join(parts)
                mw.col.decks.rename(deck, new_full_name)

        mw.col.setMod()
        mw.deckBrowser.refresh()
        self.accept()

def show_sorter_dialog():
    dialog = DeckSorterDialog(mw)
    dialog.exec()

action = QAction("Custom Deck Sort", mw)
action.triggered.connect(show_sorter_dialog)
mw.form.menuTools.addAction(action)
