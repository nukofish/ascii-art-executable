#include <ctype.h>
#include <stdio.h>
#include <string.h>
#define MAX_WORDS 512
#define MAX_LEN 24
#define TOP 5


struct /*(*/ entry /*&*/ { /*(*/ char /*)*/ word /*&*/ [ /*(*/ MAX_LEN /*:*/ ] /*&*/ ; /*(*/ unsigned /*o*/ count /*-*/ ; /*o*/ } /*.*/ ; /*)*/ static //:o+-x=()&.:o+-x=()&.:o+-x
struct /*.*/ entry /*o*/ table /*-*/ [ /*o*/ MAX_WORDS /*)*/ ] /*=*/ ; /*-*/ static /*(*/ size_t /*.*/ used /*:*/ ; /*&*/ static //o+-x=()&.:o+-x=()&.:o+-x=()&.:o+-x=()&.:o+-x=()
void /*:*/ add_word /*=*/ ( /*-*/ const /*=*/ char /*(*/ * /*x*/ word /*=*/ ) /*-*/ { /*o*/ for /*o*/ ( /*.*/ size_t /*+*/ i /*:*/ = /*&*/ 0 /*(*/ ; /*x*/ i< /*-*/ used /*x*/ ;i
++) /*+*/ { /*:*/ if /*.*/ ( /*)*/ strcmp( /*o*/ table /*-*/ [ /*o*/ i /*.*/ ] /*)*/ .word /*.*/ , /*)*/ word /*&*/ ) /*(*/ ==0 /*(*/ ) /*x*/ { /*+*/ table /*x*/ [i /*-*/ ].count
++ /*x*/ ;                          return /*x*/ ;} /*-*/                     } /*o*/ if(                                used /*)*/ <                                      //+-x=(
MAX_WORDS /**/                      /*:o+-x=(*/ ) /*x*/ {                     strcpy /*.:o+*/                                (table                                        //=()&.
[ /*.*/ used                        /*-x*/ ] /*+*/ .word                      /*=(*/ ,word                               /*&.:o*/ );                                         table
[ /*+*/       /*x=(*/ used /*)&.:o*/       ++ /**/       ] /*.*/ . /*)*/ count          =1            ; /*x*/ } /*+*/ }         static        /**/ int /*o*/ before //x=()&.:o+-x=
( /*=*/       const /*-*/ struct           /*()&*/       /**/ entry /*o+-x=(*/         *a            , /*(*/ const /*&.*/       struct        /*=()&.:o+-*/ entry /*=*/ * /*-*/ b
){ /**/         return /*.:o+-x=()*/        a->              count /*-x=()&.*/       !=b /**/          ->count /*)&.:o+*/       /*x*/ ?         a /*+*/ -> /*o*/ count> /*x*/ b //
-> /**/       count /*.*/ : /*)&.:*/       strcmp        /*()&.:o+-*/ (a /*+*/       -> /*)*/       word /*x*/ ,b-> /*=*/       /*)&.*/       word /*(*/ ) /*x*/ <0 /*-*/ ;}static
void          /*()&.:o+-x=()&.:*/ sort /*o*/ (            struct /*)&.:o+-x=*/        entry         /*+-x=(*/ *items /**/       /*:o+*/          , /*.*/ long /*:*/ low /*:*/ , //
long              high /*&*/ ) /*(*/ { /*x*/ if(         low /*(*/ >=high /**/       /*:o+-*/        ) /*&*/ {return /**/       /*-x=*/        ; /*:*/ } /*&*/ struct /*o*/ entry
pivot         /*+-x=()&.:o+-x=(*/ =items /*.:o+-*/       /**/ [ /*+*/ (low            +high         /*&.:o+*/ ) /*:*/ /2]          ;          long /*=*/ i /*-*/ = /*o*/ low,j //-
= /*-*/       high /*:*/ ; /*&*/ while /*:*/ (           i /*:*/ <= /*.*/ j){        while          /*o+-x*/ (before /**/       /*.:o*/                             /**/ ( /*+*/ &
items         /*&.:*/ [ /*&*/ i /*(*/ ] /*x*/ ,&         pivot /*)*/ ) /*=*/ )       i++;           while /*:*/ ( /*&.:*/       before                              /*&.:o+-*/ (
& /*.*/       pivot /*)*/ , /*=*/ & /*-*/ items             [ /*.*/ j /*)*/ ])       )j--            ; /*:*/ if /*.*/ (i        <=j                                  ) /*x*/ { //+
struct        /*x=*/ entry /*)*/ swap /*&.:o+-x=*/         = /*o*/ items /*-*/         [i            ] /*-*/ ;items /*(*/           [                               i++ /*&*/ ] //
= /*=*/       items /*-*/ [ /*o*/ j] /*:*/ ;items        /*:o+-*/ [ /*o*/ j--          ] =           swap /*.*/ ;} /*&.*/       } /*-*/       sort /*:*/ ( /*&*/ items /*:*/ , //&
low             , /*x*/ j /*+*/ ) /*:*/ ;sort(           items /*.*/ , /*)*/ i       ,high          /*()&.*/ ) /*)*/ ; }        int             main /*=*/ ( /*-*/ void /*x*/ ) //
{ /*o*/       char /*&*/ word /*.*/ [MAX_LEN /*x*/       /*()&.:o+-x=(*/ ];            size_t       /*.:o+-x=()&*/ length       /*)&.*/       /*o+*/ = /*:*/ 0 /*&*/ ;int /*.*/ c;
/*+-x*/       unsigned /*=()&.:o+-*/       long              total /*.:o+-x=*/       =0; /**/          while /*o*/ ( /**/         (c            = /*&*/ getchar /*+*/ ( /*:*/ ) //
)!=               EOF /*)*/ ){ /*(*/       if(              isalpha /*-x=()&*/       /*:*/ (         c ) /*:*/ || /*.*/ c       == /**/       '\'' /*+*/ ) /*:*/ { /*&*/ if(length
+ /*:*/       /*+-x=(*/ 1 /*x*/ <          sizeof        /*=()*/ word /*&.:o*/        ){ /**/       word /*-*/ [ /*o+-x*/       length        /*:o+-x*/ ++] /*x*/ = /*+*/ (char //
) /*-*/        tolower /*x=()&.:o+*/          (          c /*:*/ ) /*&*/ ;}}         else             if /*(*/ (length          /*.:o*/       /**/ >0 /*o*/ ) /*.*/ { /*)*/ word[
length /*o+-*/                      /*:o*/ ] /*.*/ ='\0'                      /*+*/ ; /*:o+*/                            add_word /*x*/                                    //=()&.
( /*.*/ word                            ) /*.*/ ;total                        /*=()*/ ++;                                   length /**/                                    //&.:o+
= /*+*/ 0;}                           } /*:*/ if /*.*/ (                      length /*=()&*/                             > /*x*/ 0){                                       word
[ /*=*/ length /*&*/ ] /*(*/ = /*x*/ '\0' /*=*/ ; /*-*/ add_word /*&*/ ( /*(*/ word /*)*/ ) /*=*/ ; /*-*/ total /*=*/ ++ /*x*/ ; /*+*/ } /*:*/ sort( /*+*/ table /*x*/ , /*+*/ 0
,( /*.*/ long /*:*/ ) /*&*/ used /*.*/ - /*)*/ 1) /*(*/ ; /*x*/ printf /*)*/ ( /*=*/ "%lu words, %zu distinct\n" /*.*/ , //)&.:o+-x=()&.:o+-x=()&.:o+-x=()&.:o+-x=()&.:o+-x=()&.:o
total /*=*/ , /*-*/ used /*x*/ ); /*-*/ for /*-*/ ( /*o*/ size_t /*x*/ i /*+*/ =0 /*o*/ ; /*.*/ i /*)*/ < /*=*/ used&& /*&*/ i /*(*/ < /*x*/ TOP /*x*/ ; /*+*/ i++ /*+*/ ) /*:*/ {
printf /*.*/ ( "%-12s %u\n" /*:*/ , /*&*/ table /*:*/ [ /*&*/ i] /*)*/ . /*=*/ word /*(*/ , /*x*/ table /*(*/ [i /*=*/ ] /*-*/ . /*o*/ count /*-*/ ); /*+*/ } /*:*/ return 0;} //)
