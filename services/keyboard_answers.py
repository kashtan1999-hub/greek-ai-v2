"""Accept keyboard aliases only when naming/identifying one letter."""
import re
import unicodedata
# Sound/name equivalents, not a blanket conversion of Greek words.
ALIASES = {'ρ': {'r', 'р', 'p'}, 'α': {'a', 'а'}, 'β': {'b', 'в'},
           'ε': {'e', 'е'}, 'ι': {'i', 'и'}, 'κ': {'k', 'к'},
           'μ': {'m', 'м'}, 'ν': {'n', 'н'}, 'ο': {'o', 'о'},
           'τ': {'t', 'т'}, 'χ': {'x', 'х'}}

def letters(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalpha())

def equivalent_letter(exercise, answer):
    question = str(exercise.get('question') or '').casefold()
    if not re.search(r'letter|symbol|букв|символ', question): return False
    if re.search(r'pronounc|sound|произнош|звук|spell|напис.*слов', question): return False
    expected = letters(str(exercise.get('correct_answer') or ''))
    actual = letters(answer)
    if not expected or len(set(expected)) != 1 or len(expected) > 2: return False
    if not actual or len(set(actual)) != 1 or len(actual) > 2: return False
    char = expected[0]
    return actual[0] == char or actual[0] in ALIASES.get(char, set())


def equivalent_boolean(exercise, answer):
    q = str(exercise.get('question') or '').casefold()
    if not re.search(r'true.?false|верно|неверно|да.*нет|правда|истин', q): return False
    true = {'true','yes','да','+','верно','правильно','αληθές','σωστό'}
    false = {'false','no','нет','-','−','неверно','неправильно','λάθος','ψευδές'}
    key = str(exercise.get('correct_answer') or '').strip().casefold()
    value = answer.strip().casefold()
    return (key in true and value in true) or (key in false and value in false)
