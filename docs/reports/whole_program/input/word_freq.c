/* Word frequency: count words from stdin and print the most common ones. */
#include <ctype.h>
#include <stdio.h>
#include <string.h>

#define MAX_WORDS 512
#define MAX_LEN 24
#define TOP 5

struct entry {
    char word[MAX_LEN];
    unsigned count;
};

static struct entry table[MAX_WORDS];
static size_t used;

static void add_word(const char *word) {
    for (size_t i = 0; i < used; i++) {
        if (strcmp(table[i].word, word) == 0) {
            table[i].count++;
            return;
        }
    }
    if (used < MAX_WORDS) {
        strcpy(table[used].word, word);
        table[used++].count = 1;
    }
}

static int before(const struct entry *a, const struct entry *b) {
    return a->count != b->count ? a->count > b->count : strcmp(a->word, b->word) < 0;
}

/* Recursive quicksort, as usually taught in class. */
static void sort(struct entry *items, long low, long high) {
    if (low >= high) {
        return;
    }
    struct entry pivot = items[(low + high) / 2];
    long i = low, j = high;
    while (i <= j) {
        while (before(&items[i], &pivot)) i++;
        while (before(&pivot, &items[j])) j--;
        if (i <= j) {
            struct entry swap = items[i];
            items[i++] = items[j];
            items[j--] = swap;
        }
    }
    sort(items, low, j);
    sort(items, i, high);
}

int main(void) {
    char word[MAX_LEN];
    size_t length = 0;
    int c;
    unsigned long total = 0;

    while ((c = getchar()) != EOF) {
        if (isalpha(c) || c == '\'') {
            if (length + 1 < sizeof word) {
                word[length++] = (char)tolower(c);
            }
        } else if (length > 0) {
            word[length] = '\0';
            add_word(word);
            total++;
            length = 0;
        }
    }
    if (length > 0) {
        word[length] = '\0';
        add_word(word);
        total++;
    }

    sort(table, 0, (long)used - 1);
    printf("%lu words, %zu distinct\n", total, used);
    for (size_t i = 0; i < used && i < TOP; i++) {
        printf("%-12s %u\n", table[i].word, table[i].count);
    }
    return 0;
}
