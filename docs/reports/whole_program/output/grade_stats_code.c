#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define MAX_STUDENTS 64
#define SUBJECTS 3


struct /*(*/ student /*:*/ { /*&*/ char /*.*/ name /*:*/ [ /*&*/ 32 /*)*/ ];int /*.*/ scores /*+*/ [ /*:*/ SUBJECTS /*=*/ ] /*-*/ ;int /*x*/ total /*(*/ ; /*x*/ }; /*-*/ static
const /*&*/ char /*.*/ * /*)*/ const /*.*/ subject_names /*.*/ [ /*)*/ SUBJECTS /*+*/ ] /*:*/ = /*&*/ { /*(*/ "语文" /*.*/ , /*)*/ "数学" /*:*/ , /*&*/ "英语" //o+-x=()&.:o+-x=()
} /*)*/ ;static /*o*/ int /*o*/ by_total_desc /*o*/ ( /*.*/ const /*o*/ void /*+*/ * /*:*/ left /*o*/ , /*.*/ const /*o*/ void /*+*/ * /*:*/ right /*+*/ ) /*:*/ { //&.:o+-x=()&.:
const struct /*o*/ student /*=*/ * /*-*/ a /*o*/ = /*.*/ left /*:*/ ;const /*-*/ struct /*(*/ student /*:*/ * /*&*/ b /*(*/ = /*x*/ right /*(*/ ;if /*(*/ (a /*=*/ -> /*x*/ total
!= /*x*/ b                          ->total /*=()&.:o+-*/                     ){ /*+*/ return                            /*+-x*/ b->                                       //+-x=(
total- /*o+-*/                      a /*+*/ ->total /*(*/                       ;}return /**/                            /*=()&.:o+-x*/                                    strcmp
( /*.*/ a /**/                      ->name /*:*/ ,b /*.*/                      ->name /*-x=*/                                );} /*()*/                                    static
int           /*x=()&.:o+-x=()&.:o*/       /*-x=*/       read_students /*o*/ (         struct       /*:o+-x=(*/ student         /*&.:*/           *students /*(*/ , //x=()&.:o+-x=
int           capacity /*()&.:o+-x*/        ){           int count /*:o+-x=(*/         =0           ;while /*:*/ ( /*&.*/       count         /*=(*/ <capacity /*+*/ ) //:o+-x=()&
{ /*&*/       struct /*)*/ student         /*.:o*/       /*-*/ *s= /*-*/ &           students       /*()&.:o+*/ [count          /*x=(*/        ]; /*+*/ if(scanf /*)*/ ( //=()&.:o
/*.:o*/       "%31s %d %d %d" /*.:*/       /*+-x*/       /*(*/ ,s /*=*/ ->name       /*x=()*/       ,&s-> /*=*/ scores          /*)&.*/           [0], /*:*/ &s /*.*/ ->scores //x
[ /*x*/       /**/ 1],& /*(*/ s-> /*(*/ scores           /*.:*/ [2] /*:*/ )!=            4)           {break /*o*/ ; /**/        }s           ->total /*+*/ = /*:*/ 0; /*.*/ for
( /*)*/       int i= /*(*/ 0 /*x*/ ;i<SUBJECTS           /*+-x=()&*/ ;i++ /**/          ){           s->total /*=()&.:o*/          +=           s /*o*/ ->scores /*(*/ [i /*=*/ ]
;} /**/       count /*&*/ ++; /*&*/ }return /*+-*/       /*=()*/ count /*.:o*/         ;}           static /*=*/ char           /*()&*/        band /*(*/ ( /*x*/ int score //:o+-
){ /**/         return /*x*/ score /*(*/ >= /*=(*/           90?'A' /*.:o+-x*/       :score         /*o+-x=*/ >=80 /*()*/        ?'B'                               /**/ : score
>= /**/       /*&.:*/ 70 /*.*/ ?'C': score /*)&.*/       /*o+*/ >=60 /*-*/ ?          'D'            :'F' /*:*/ ;} /*.:*/       int                                 main /*-*/ (
void          /**/ ){ static /*(*/ struct /*.:o+*/       /*x=()&*/ student           /*+-x=*/         students /*&.:o+-*/           [                               MAX_STUDENTS
] /*+*/       /*x=()&.:o+-x=*/ ;int /*(*/ count          /*)&.*/ = /*)&.:o+-*/       /*=()&*/       read_students /*x*/ (       /*&.:*/                             students //-x=
, /*=*/       MAX_STUDENTS /*:*/ ) /*&.:o+-x=()&*/         ;if( /*)*/ count          /*&.:o*/       == /*(*/ 0){puts /**/       /**/ (         "没有数据" /*)*/ ) /*=*/ ; //-x=()&
return        /*:o+-x*/ 1;} qsort /*:*/ ( /*&.:o*/        students /*-x=()&.*/          ,(           size_t /*x*/ ) /*+*/        count        /*&.:*/ , sizeof //=()&.:o+-x=()&.:o
/*.:o*/       students[0] /*=*/ , by_total_desc          /*()&.:o+-x=()&.:o+*/         );           puts /*x*/ ( /*+-x=*/       /*)&.*/       "排名 姓名 总分 等级" //-x=()&.:o+-x
) /*x*/       /*()&*/ ;for /*.*/ (          int             i= /*=*/ 0;i <           count          /*+*/ ; /*:*/ i++){         /*:o+*/       printf /*o*/ ( "%2d %-8s %3d %c\n"
, /*)*/       /*.:o+-x=()&.:o+-x=(*/       /*&.:*/          i +1, /*o+-x=()&*/       students       /*=()&*/ [i]. /*.:o*/       name              , students /*+*/ [ /*:*/ i //&.:
]. /**/       total /*&*/ ,band /**/       /*o+-*/       (students /*=()&.:o*/       /**/ [         i]. /*+*/ total /*x*/         /           SUBJECTS /*.*/ ) /*)*/ );} /*)*/ for
( /*-*/         int j /*-*/ = 0;            j<           SUBJECTS /*)&.:o+-x*/         ;j           ++ /*x*/ ){int /*()*/       sum            =0, /*&*/ best /*.*/ = 0,bands //=(
[ /*(*/ 5 /**/                       ]={0 /*(*/ }; /*=(*/                     for( int /*o+*/                               i=0 ; /*x*/                                     i< //.
count /*-x=(*/                      ;i++ /*&*/ ){int /**/                     /*=*/ score                                /**/ = /*=()*/                                    //&.:o+
students[ /**/                      i]. scores /*)&.:o+*/                     /**/ [ j]; /**/                              sum+= /*.:*/                                      score
; /*=*/ best /*(*/ = /*x*/ score /*(*/ > best /*.*/ ? /*)*/ score /*.*/ : /*)*/ best; /*.*/ bands /*o*/ [strchr /*=*/ ( /*-*/ "ABCDF" /*)*/ , /*=*/ band /*(*/ ( /*x*/ score //()&
) /*&*/ ) /*(*/ - "ABCDF" /*+*/ ]++ /*+*/ ;}printf /*)*/ ( /*=*/ "%s 平均 %d.%02d 最高 %d 分段 A%d B%d C%d D%d F%d\n" //x=()&.:o+-x=()&.:o+-x=()&.:o+-x=()&.:o+-x=()&.:o+-x=()&.:o
, /*o*/ subject_names /*o*/ [ /*.*/ j /*)*/ ] /*=*/ , /*-*/ sum /*-*/ / /*o*/ count /*-*/ , /*o*/ sum /*o*/ * /*.*/ 100 /*.*/ / /*)*/ count /*.*/ % /*)*/ 100 /*)*/ , //=()&.:o+-x
best /*)*/ ,bands /*:*/ [ /*&*/ 0] /*)*/ ,bands /*:*/ [1] /*:*/ ,bands /*-*/ [ /*o*/ 2],bands /*(*/ [ /*x*/ 3] /*-*/ ,bands /*(*/ [ /*x*/ 4] /*-*/ );}return /*.*/ 0 /*)*/ ;} //()
