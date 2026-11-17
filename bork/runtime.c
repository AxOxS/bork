/* Bork runtime, pasted at the top of every generated C file. It mirrors
   values.py and builtins.py, and has to agree with them on every detail. */
#define _POSIX_C_SOURCE 200809L
#include <inttypes.h>
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

typedef uint8_t bork_unit;
/* Code points, like a Python str, so len and indexing count characters. */
typedef struct BorkStr { int64_t len; uint32_t cp[]; } BorkStr;
struct BorkArr;
typedef union BorkV {
    int64_t i; double f; bool b; bork_unit u;
    BorkStr *s; struct BorkArr *a; void *p; void (*fn)(void);
} BorkV;
typedef struct BorkArr { int64_t len, cap; BorkV *data; } BorkArr;

/* Through uint64_t, so wrapping is defined even without -fwrapv. */
#define BORK_ADD(a, b) ((int64_t)((uint64_t)(a) + (uint64_t)(b)))
#define BORK_SUB(a, b) ((int64_t)((uint64_t)(a) - (uint64_t)(b)))
#define BORK_MUL(a, b) ((int64_t)((uint64_t)(a) * (uint64_t)(b)))
#define BORK_NEG(a)    ((int64_t)(0u - (uint64_t)(a)))

/* ---- frames and runtime errors (vm.py: VM.traceback, VM.fail) ----------- */
typedef struct BorkFrame { const char *name; int line; struct BorkFrame *parent; } BorkFrame;
static BorkFrame *bork_top;
static int64_t bork_depth;
static const char *bork_source = "<input>";
#define BORK_MAX_FRAMES 20000

typedef struct { uint32_t *cp; int64_t len, cap; } BorkBuf;
static void bork_put(BorkBuf *b, uint32_t c);
static void bork_put_ascii(BorkBuf *b, const char *s);
static void bork_write_utf8(FILE *out, const uint32_t *cp, int64_t n);

static void bork_put_count(FILE *out, int64_t n) {          /* f"{n:,}" */
    char digits[32];
    int len = snprintf(digits, sizeof digits, "%" PRId64, n);
    for (int i = 0; i < len; i++) {
        if (i > 0 && (len - i) % 3 == 0) fputc(',', out);
        fputc(digits[i], out);
    }
}

static void bork_traceback(void) {
    const int64_t head = 8, tail = 4;
    int64_t n = 0;
    for (BorkFrame *f = bork_top; f; f = f->parent) n++;
    bool cut = n > head + tail + 1;
    int64_t i = 0;
    for (BorkFrame *f = bork_top; f; f = f->parent, i++) {
        if (cut && i == head) {
            fputs("    ... ", stderr);
            bork_put_count(stderr, n - head - tail);
            fputs(" frames omitted ...\n", stderr);
        }
        if (cut && i >= head && i < n - tail) continue;
        fprintf(stderr, "    at %s (%s:%d)\n", f->name, bork_source, f->line);
    }
}

static _Noreturn void bork_fail_buf(BorkBuf *msg) {
    fflush(stdout);
    fputs("runtime error: ", stderr);
    bork_write_utf8(stderr, msg->cp, msg->len);
    fputc('\n', stderr);
    bork_traceback();
    fflush(stderr);
    exit(70);
}

static _Noreturn void bork_fail(const char *fmt, ...) {
    char text[512];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(text, sizeof text, fmt, ap);
    va_end(ap);
    BorkBuf b = {0};
    bork_put_ascii(&b, text);
    bork_fail_buf(&b);
}

#define BORK_ENTER(nm) BorkFrame fr; bork_enter(&fr, nm)
#define BORK_LEAVE() (bork_top = fr.parent, bork_depth--)

static inline void bork_enter(BorkFrame *f, const char *name) {
    /* The VM checks this in the caller, before the callee has a frame, so the
       traceback starts at the call site. */
    if (bork_depth - 1 >= BORK_MAX_FRAMES)
        bork_fail("call stack overflow (limit %d frames)", BORK_MAX_FRAMES);
    f->name = name;
    f->line = 0;
    f->parent = bork_top;
    bork_top = f;
    bork_depth++;
}

static _Noreturn void bork_uninit(const char *name) {
    bork_fail("'%s' is used before it is initialised", name);
}

/* Nothing is ever freed: the VM has Python's collector, this has none. */
static void *bork_alloc(size_t n) {
    void *p = malloc(n ? n : 1);
    if (!p) bork_fail("out of memory");
    return p;
}

/* ---- integer semantics (values.py: wrap64, idiv, imod) ------------------ */
static inline int64_t bork_idiv(int64_t a, int64_t b) {
    if (b == 0) bork_fail("integer division by zero");
    if (b == -1) return BORK_NEG(a);           /* MIN / -1 wraps to MIN */
    return a / b;                              /* C truncates toward zero */
}

static inline int64_t bork_imod(int64_t a, int64_t b) {
    if (b == 0) bork_fail("integer remainder by zero");
    if (b == -1) return 0;
    return a % b;                              /* sign follows the dividend */
}

static inline int64_t bork_iabs(int64_t a) { return a < 0 ? BORK_NEG(a) : a; }

/* vm.py: fmod. Float division needs no helper: C's `/` is IEEE-754. */
static inline double bork_fmod(double a, double b) {
    if (b == 0.0 || a != a || b != b || isinf(a)) return NAN;
    return fmod(a, b);
}

/* ---- text buffers and output -------------------------------------------- */
static void bork_put(BorkBuf *b, uint32_t c) {
    if (b->len == b->cap) {
        b->cap = b->cap ? b->cap * 2 : 32;
        uint32_t *grown = realloc(b->cp, (size_t)b->cap * sizeof *grown);
        if (!grown) bork_fail("out of memory");
        b->cp = grown;
    }
    b->cp[b->len++] = c;
}

static void bork_put_ascii(BorkBuf *b, const char *s) {
    while (*s) bork_put(b, (unsigned char)*s++);
}

static void bork_put_cps(BorkBuf *b, const uint32_t *cp, int64_t n) {
    for (int64_t i = 0; i < n; i++) bork_put(b, cp[i]);
}

static BorkStr *bork_str_new(int64_t n) {
    BorkStr *s = bork_alloc(sizeof(BorkStr) + (size_t)n * sizeof(uint32_t));
    s->len = n;
    return s;
}

static BorkStr *bork_buf_take(BorkBuf *b) {
    BorkStr *s = bork_str_new(b->len);
    if (b->len) memcpy(s->cp, b->cp, (size_t)b->len * sizeof(uint32_t));
    free(b->cp);
    b->cp = NULL;
    b->len = b->cap = 0;
    return s;
}

static void bork_write_utf8(FILE *out, const uint32_t *cp, int64_t n) {
    for (int64_t i = 0; i < n; i++) {
        uint32_t c = cp[i];
        if (c < 0x80) {
            putc((int)c, out);
        } else if (c < 0x800) {
            putc((int)(0xC0 | (c >> 6)), out);
            putc((int)(0x80 | (c & 0x3F)), out);
        } else if (c < 0x10000) {
            putc((int)(0xE0 | (c >> 12)), out);
            putc((int)(0x80 | ((c >> 6) & 0x3F)), out);
            putc((int)(0x80 | (c & 0x3F)), out);
        } else {
            putc((int)(0xF0 | (c >> 18)), out);
            putc((int)(0x80 | ((c >> 12) & 0x3F)), out);
            putc((int)(0x80 | ((c >> 6) & 0x3F)), out);
            putc((int)(0x80 | (c & 0x3F)), out);
        }
    }
}

static void bork_print(BorkStr *s) {
    bork_write_utf8(stdout, s->cp, s->len);
    putc('\n', stdout);
}

static void bork_print_int(int64_t v) { printf("%" PRId64 "\n", v); }

/* ---- strings ------------------------------------------------------------ */
static BorkStr *bork_str_ascii(const char *text, int64_t n) {
    BorkStr *s = bork_str_new(n);
    for (int64_t i = 0; i < n; i++) s->cp[i] = (unsigned char)text[i];
    return s;
}

static BorkStr *bork_str_cps(const uint32_t *cp, int64_t n) {
    BorkStr *s = bork_str_new(n);
    if (n) memcpy(s->cp, cp, (size_t)n * sizeof(uint32_t));
    return s;
}

static BorkStr *bork_char_cache[256];

static BorkStr *bork_char(uint32_t c) {
    if (c < 256 && bork_char_cache[c]) return bork_char_cache[c];
    BorkStr *s = bork_str_new(1);
    s->cp[0] = c;
    if (c < 256) bork_char_cache[c] = s;
    return s;
}

static BorkStr *bork_concat(BorkStr *a, BorkStr *b) {
    if (a->len == 0) return b;
    if (b->len == 0) return a;
    BorkStr *s = bork_str_new(a->len + b->len);
    memcpy(s->cp, a->cp, (size_t)a->len * sizeof(uint32_t));
    memcpy(s->cp + a->len, b->cp, (size_t)b->len * sizeof(uint32_t));
    return s;
}

static bool bork_str_eq(BorkStr *a, BorkStr *b) {
    return a->len == b->len && memcmp(a->cp, b->cp, (size_t)a->len * sizeof(uint32_t)) == 0;
}

static int bork_str_cmp(BorkStr *a, BorkStr *b) {        /* code point order */
    int64_t n = a->len < b->len ? a->len : b->len;
    for (int64_t i = 0; i < n; i++)
        if (a->cp[i] != b->cp[i]) return a->cp[i] < b->cp[i] ? -1 : 1;
    return a->len < b->len ? -1 : a->len > b->len ? 1 : 0;
}

static _Noreturn void bork_index_fail(int64_t i, int64_t n, const char *kind) {
    bork_fail("index %" PRId64 " is out of bounds for %s of length %" PRId64, i, kind, n);
}

static BorkStr *bork_str_index(BorkStr *s, int64_t i) {
    if (i < 0 || i >= s->len) bork_index_fail(i, s->len, "string");
    return bork_char(s->cp[i]);
}

/* ---- arrays ------------------------------------------------------------- */
static BorkArr *bork_arr_new(int64_t n) {
    BorkArr *a = bork_alloc(sizeof *a);
    a->len = a->cap = n;
    a->data = n ? bork_alloc((size_t)n * sizeof(BorkV)) : NULL;
    return a;
}

static inline BorkV bork_arr_get(BorkArr *a, int64_t i) {
    if (i < 0 || i >= a->len) bork_index_fail(i, a->len, "array");
    return a->data[i];
}

static inline void bork_arr_set(BorkArr *a, int64_t i, BorkV v) {
    if (i < 0 || i >= a->len) bork_index_fail(i, a->len, "array");
    a->data[i] = v;
}

static void bork_arr_push(BorkArr *a, BorkV v) {
    if (a->len == a->cap) {
        a->cap = a->cap ? a->cap * 2 : 8;
        BorkV *grown = realloc(a->data, (size_t)a->cap * sizeof(BorkV));
        if (!grown) bork_fail("out of memory");
        a->data = grown;
    }
    a->data[a->len++] = v;
}

static BorkV bork_arr_pop(BorkArr *a) {
    if (a->len == 0) bork_fail("pop from empty array");
    return a->data[--a->len];
}

/* ---- display (values.py: to_display, to_repr, format_float) ------------- */
static void bork_show_int_raw(BorkBuf *b, int64_t v) {
    char text[32];
    snprintf(text, sizeof text, "%" PRId64, v);
    bork_put_ascii(b, text);
}

/* Python's repr(float): the shortest digits that read back as the same double,
   in fixed notation when the decimal point lands in (-4, 16], else exponent. */
static void bork_show_float_raw(BorkBuf *b, double v) {
    if (v != v) { bork_put_ascii(b, "nan"); return; }
    if (isinf(v)) { bork_put_ascii(b, v > 0 ? "inf" : "-inf"); return; }
    if (v == trunc(v) && fabs(v) < 1e16) {
        char text[40];
        snprintf(text, sizeof text, "%s%" PRId64 ".0", signbit(v) ? "-" : "", (int64_t)fabs(v));
        bork_put_ascii(b, text);
        return;
    }
    char sci[40];
    for (int prec = 1; prec <= 17; prec++) {
        snprintf(sci, sizeof sci, "%.*e", prec - 1, v);
        if (strtod(sci, NULL) == v) break;
    }
    const char *p = sci;
    if (*p == '-') { bork_put(b, '-'); p++; }
    char digits[24];
    int nd = 0;
    for (; *p && *p != 'e'; p++)
        if (*p != '.') digits[nd++] = *p;
    int decpt = atoi(p + 1) + 1;
    while (nd > 1 && digits[nd - 1] == '0') nd--;
    if (decpt > -4 && decpt <= 16) {
        if (decpt <= 0) {
            bork_put_ascii(b, "0.");
            for (int i = 0; i < -decpt; i++) bork_put(b, '0');
            for (int i = 0; i < nd; i++) bork_put(b, (uint32_t)digits[i]);
        } else if (decpt >= nd) {
            for (int i = 0; i < nd; i++) bork_put(b, (uint32_t)digits[i]);
            for (int i = nd; i < decpt; i++) bork_put(b, '0');
            bork_put_ascii(b, ".0");
        } else {
            for (int i = 0; i < nd; i++) {
                if (i == decpt) bork_put(b, '.');
                bork_put(b, (uint32_t)digits[i]);
            }
        }
    } else {
        bork_put(b, (uint32_t)digits[0]);
        if (nd > 1) {
            bork_put(b, '.');
            for (int i = 1; i < nd; i++) bork_put(b, (uint32_t)digits[i]);
        }
        char exp[16];
        snprintf(exp, sizeof exp, "e%c%02d", decpt - 1 < 0 ? '-' : '+', abs(decpt - 1));
        bork_put_ascii(b, exp);
    }
}

static void bork_show_str_raw(BorkBuf *b, BorkStr *s, bool repr) {
    if (!repr) { bork_put_cps(b, s->cp, s->len); return; }
    bork_put(b, '"');
    for (int64_t i = 0; i < s->len; i++) {
        uint32_t c = s->cp[i];
        if (c == '\\') bork_put_ascii(b, "\\\\");
        else if (c == '"') bork_put_ascii(b, "\\\"");
        else if (c == '\n') bork_put_ascii(b, "\\n");
        else if (c == '\t') bork_put_ascii(b, "\\t");
        else bork_put(b, c);
    }
    bork_put(b, '"');
}

/* Show functions take the value as a BorkV so that every type has the same
   signature; `repr` is true inside containers, where strings are quoted. */
typedef void (*BorkShow)(BorkBuf *, BorkV, bool);

static void bork_show_int(BorkBuf *b, BorkV v, bool repr) { (void)repr; bork_show_int_raw(b, v.i); }
static void bork_show_float(BorkBuf *b, BorkV v, bool repr) { (void)repr; bork_show_float_raw(b, v.f); }
static void bork_show_bool(BorkBuf *b, BorkV v, bool repr) { (void)repr; bork_put_ascii(b, v.b ? "true" : "false"); }
static void bork_show_unit(BorkBuf *b, BorkV v, bool repr) { (void)v; (void)repr; bork_put_ascii(b, "unit"); }
static void bork_show_str(BorkBuf *b, BorkV v, bool repr) { bork_show_str_raw(b, v.s, repr); }

static BorkStr *bork_to_str(BorkShow show, BorkV v) {
    BorkBuf b = {0};
    show(&b, v, false);
    return bork_buf_take(&b);
}

/* ---- conversions (builtins.py: _n_int, _n_float) ------------------------ */
static bool bork_isspace(uint32_t c) {                    /* Python's str.isspace */
    return (c >= 0x09 && c <= 0x0D) || (c >= 0x1C && c <= 0x20) || c == 0x85 || c == 0xA0
        || c == 0x1680 || (c >= 0x2000 && c <= 0x200A) || c == 0x2028 || c == 0x2029
        || c == 0x202F || c == 0x205F || c == 0x3000;
}

/* Python's repr(str), for failed-parse messages. Escapes the common
   unprintable characters, not the whole Unicode database. */
static void bork_put_pyrepr(BorkBuf *b, BorkStr *s) {
    bool has_single = false, has_double = false;
    for (int64_t i = 0; i < s->len; i++) {
        if (s->cp[i] == '\'') has_single = true;
        if (s->cp[i] == '"') has_double = true;
    }
    uint32_t quote = (has_single && !has_double) ? '"' : '\'';
    bork_put(b, quote);
    for (int64_t i = 0; i < s->len; i++) {
        uint32_t c = s->cp[i];
        char esc[16];
        if (c == '\\') bork_put_ascii(b, "\\\\");
        else if (c == quote) { bork_put(b, '\\'); bork_put(b, c); }
        else if (c == '\n') bork_put_ascii(b, "\\n");
        else if (c == '\r') bork_put_ascii(b, "\\r");
        else if (c == '\t') bork_put_ascii(b, "\\t");
        else if (c < 0x20 || (c >= 0x7F && c <= 0xA0) || c == 0xAD) {
            snprintf(esc, sizeof esc, "\\x%02x", (unsigned)c);
            bork_put_ascii(b, esc);
        } else if (c == 0x1680 || (c >= 0x2000 && c <= 0x200F) || (c >= 0x2028 && c <= 0x202F)
                   || (c >= 0x205F && c <= 0x2064) || c == 0x3000 || c == 0xFEFF
                   || (c >= 0xD800 && c <= 0xDFFF)) {
            snprintf(esc, sizeof esc, "\\u%04x", (unsigned)c);
            bork_put_ascii(b, esc);
        } else {
            bork_put(b, c);
        }
    }
    bork_put(b, quote);
}

static _Noreturn void bork_parse_fail(BorkStr *s, const char *what) {
    BorkBuf b = {0};
    bork_put_ascii(&b, "cannot parse ");
    bork_put_pyrepr(&b, s);
    bork_put_ascii(&b, " as ");
    bork_put_ascii(&b, what);
    bork_fail_buf(&b);
}

static inline bool bork_isdigit(uint32_t c) { return c >= '0' && c <= '9'; }

/* Copies the stripped text as ASCII, or fails if any character is not ASCII. */
static int64_t bork_strip_ascii(BorkStr *s, char *out, int64_t cap, const char *what) {
    int64_t i = 0, j = s->len;
    while (i < j && bork_isspace(s->cp[i])) i++;
    while (j > i && bork_isspace(s->cp[j - 1])) j--;
    if (j - i >= cap) bork_parse_fail(s, what);
    int64_t n = 0;
    for (; i < j; i++) {
        if (s->cp[i] >= 0x80) bork_parse_fail(s, what);
        out[n++] = (char)s->cp[i];
    }
    out[n] = '\0';
    return n;
}

/* Digits with single underscores between them, as Python's int() and float()
   accept. Returns the length consumed, or 0 if there is no digit at p. */
static int64_t bork_digitpart(const char *p) {
    int64_t n = 0;
    if (!bork_isdigit((unsigned char)p[0])) return 0;
    while (bork_isdigit((unsigned char)p[n]) || (p[n] == '_' && bork_isdigit((unsigned char)p[n + 1])))
        n++;
    return n;
}

static int64_t bork_parse_int(BorkStr *s) {
    char text[4096];
    int64_t n = bork_strip_ascii(s, text, sizeof text, "int");
    const char *p = text;
    bool neg = false;
    if (*p == '+' || *p == '-') neg = *p++ == '-';
    int64_t digits = bork_digitpart(p);
    if (digits == 0 || (p - text) + digits != n) bork_parse_fail(s, "int");
    uint64_t acc = 0;                                     /* wraps mod 2^64 */
    for (int64_t i = 0; i < digits; i++)
        if (p[i] != '_') acc = acc * 10u + (uint64_t)(p[i] - '0');
    return neg ? (int64_t)(0u - acc) : (int64_t)acc;
}

static bool bork_word_is(const char *p, const char *word) {
    for (; *word; p++, word++)
        if ((*p | 0x20) != *word) return false;
    return *p == '\0';
}

static double bork_parse_float(BorkStr *s) {
    char text[4096], clean[4096];
    int64_t n = bork_strip_ascii(s, text, sizeof text, "float");
    const char *p = text;
    bool neg = false;
    if (*p == '+' || *p == '-') neg = *p++ == '-';
    if (bork_word_is(p, "inf") || bork_word_is(p, "infinity")) return neg ? -INFINITY : INFINITY;
    if (bork_word_is(p, "nan")) return NAN;
    const char *q = p;
    int64_t whole = bork_digitpart(q), frac = 0;
    q += whole;
    if (*q == '.') {
        q++;
        frac = bork_digitpart(q);
        q += frac;
    }
    if (whole == 0 && frac == 0) bork_parse_fail(s, "float");
    if (*q == 'e' || *q == 'E') {
        q++;
        if (*q == '+' || *q == '-') q++;
        int64_t exp = bork_digitpart(q);
        if (exp == 0) bork_parse_fail(s, "float");
        q += exp;
    }
    if (q != text + n) bork_parse_fail(s, "float");
    int64_t m = 0;
    for (const char *c = text; *c; c++)
        if (*c != '_') clean[m++] = *c;
    clean[m] = '\0';
    return strtod(clean, NULL);
}

static int64_t bork_float_to_int(double v) {
    if (v != v || isinf(v)) {
        BorkBuf b = {0};
        bork_put_ascii(&b, "cannot convert ");
        bork_show_float_raw(&b, v);
        bork_put_ascii(&b, " to int");
        bork_fail_buf(&b);
    }
    double t = trunc(v);
    if (t >= -9223372036854775808.0 && t < 9223372036854775808.0) return (int64_t)t;
    double m = fmod(t, 18446744073709551616.0);           /* exact for doubles this big */
    if (m < 0) m += 18446744073709551616.0;
    return (int64_t)(uint64_t)m;
}

/* ---- the other builtins (builtins.py) ----------------------------------- */
static double bork_sqrt_float(double v) {
    if (v < 0) {
        BorkBuf b = {0};
        bork_put_ascii(&b, "sqrt of negative number ");
        bork_show_float_raw(&b, v);
        bork_fail_buf(&b);
    }
    return sqrt(v);
}

static double bork_sqrt_int(int64_t v) {
    if (v < 0) bork_fail("sqrt of negative number %" PRId64, v);
    return sqrt((double)v);
}

static BorkStr *bork_chr(int64_t c) {
    if (c < 0 || c > 0x10FFFF) bork_fail("chr: %" PRId64 " is not a valid character code", c);
    return bork_char((uint32_t)c);
}

static int64_t bork_ord(BorkStr *s) {
    if (s->len != 1)
        bork_fail("ord expects a single-character string, got length %" PRId64, s->len);
    return s->cp[0];
}

static BorkStr *bork_substr(BorkStr *s, int64_t i, int64_t j) {
    if (i < 0 || j > s->len || i > j)
        bork_fail("substr bounds [%" PRId64 ", %" PRId64 ") out of range for string of length %" PRId64,
                  i, j, s->len);
    return bork_str_cps(s->cp + i, j - i);
}

static double bork_clock(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

/* ---- end of runtime ----------------------------------------------------- */
