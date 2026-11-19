/* 成绩统计：读入学生姓名与三门成绩，输出排名、平均分和分数段。 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_STUDENTS 64
#define SUBJECTS 3

struct student {
    char name[32];
    int scores[SUBJECTS];
    int total;
};

static const char *const subject_names[SUBJECTS] = {"语文", "数学", "英语"};

static int by_total_desc(const void *left, const void *right) {
    const struct student *a = left;
    const struct student *b = right;
    if (a->total != b->total) {
        return b->total - a->total;
    }
    return strcmp(a->name, b->name);
}

static int read_students(struct student *students, int capacity) {
    int count = 0;
    while (count < capacity) {
        struct student *s = &students[count];
        if (scanf("%31s %d %d %d", s->name, &s->scores[0], &s->scores[1],
                  &s->scores[2]) != 4) {
            break;
        }
        s->total = 0;
        for (int i = 0; i < SUBJECTS; i++) {
            s->total += s->scores[i];
        }
        count++;
    }
    return count;
}

static char band(int score) {
    return score >= 90 ? 'A' : score >= 80 ? 'B' : score >= 70 ? 'C'
         : score >= 60 ? 'D' : 'F';
}

int main(void) {
    static struct student students[MAX_STUDENTS];
    int count = read_students(students, MAX_STUDENTS);
    if (count == 0) {
        puts("没有数据");
        return 1;
    }

    qsort(students, (size_t)count, sizeof students[0], by_total_desc);
    puts("排名 姓名 总分 等级");
    for (int i = 0; i < count; i++) {
        printf("%2d %-8s %3d %c\n", i + 1, students[i].name, students[i].total,
               band(students[i].total / SUBJECTS));
    }

    for (int j = 0; j < SUBJECTS; j++) {
        int sum = 0, best = 0, bands[5] = {0};
        for (int i = 0; i < count; i++) {
            int score = students[i].scores[j];
            sum += score;
            best = score > best ? score : best;
            bands[strchr("ABCDF", band(score)) - "ABCDF"]++;
        }
        printf("%s 平均 %d.%02d 最高 %d 分段 A%d B%d C%d D%d F%d\n", subject_names[j],
               sum / count, sum * 100 / count % 100, best,
               bands[0], bands[1], bands[2], bands[3], bands[4]);
    }
    return 0;
}
