#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifndef MAX_NAME
#define MAX_NAME 48
#endif
#define MAX_LINE 128


                                    enum status{TODO, //
                              DOING,DONE};typedef struct task{
                         int id;int priority;enum status state;char
                      name[MAX_NAME];struct task*next;}Task;typedef //
                   struct{Task*head;int next_id;int count;}TaskList; //:o
                static const char*status_label(enum status state){switch( //
              state){case TODO:return"待办";case DOING:return"进行中";case //+
            DONE:return"已完成";}return"?";}static void list_init(TaskList*list)
          {list->head=NULL;list->next_id=1;list->count=0;}static Task*list_add( //
         TaskList*list,const char*name,int priority){Task*task=malloc(sizeof*task);
       if(task==NULL){return NULL;}task->id=list->next_id++;task->priority=priority;
      task->state=TODO;strncpy(task->name,name,MAX_NAME-1);task->name[MAX_NAME-1]='\0'
     ;Task**link=&list->head;while(*link!=NULL&&(*link)->priority>=priority){link=&(*
    link)->next;}task->next=*link;*link=task;list->count++;assert(list->count>0);return
   task;}static Task*list_find(TaskList*list,int id){for(Task*task=list->head;task!=NULL
   ; task=task->next){if(task->id==id){return task;}}return NULL;}static int list_remove(
  TaskList*list,int id){for(Task**link=&list->head;*link!=NULL;link=&(*link)->next){if((*
 link)->id==id){Task*gone=*link;*link=gone->next;free(gone);list->count--;return 1;}}return
 0;}static /*x*/ void list_print(const TaskList*list){printf("共 %d 项任务\n",list->count);
 for( const Task*task=list->head;task!=NULL;task=task->next){printf("  #%-3d P%d %-8s %s\n"
,task ->id,task->priority,status_label(task->state),task->name);}}static void list_summary
(const TaskList*list){int totals[3]={0,0,0};for(const Task*task=list->head;task!=NULL;task
=task-> next){totals[task->state]++;}printf("待办 %d，进行中 %d，已完成 %d\n",totals[TODO //
],totals[ DOING],totals[DONE]);}static void list_free(TaskList*list){while(list->head!=NULL
){Task*next =list->head->next;free(list->head);list->head=next;}list->count=0;}static void
trim_newline( char*line){size_t length=strlen(line);while(length>0&&(line[length-1]=='\n' //
 ||line[length-1] =='\r')){line[--length]='\0';}}static int handle(TaskList*list,char*line
 ){char command[16] ;int id=0;int priority=0;int offset=0;if(sscanf(line,"%15s%n",command,&
 offset)!=1){return 1;}if(strcmp(command,"add")==0){if(sscanf(line+offset,"%d %n",&priority
  ,&offset)==1&& /*-*/ priority>=0){char*name=line+offset;name+=strspn(name," ");Task*task
   =list_add(list,name, priority);if(task!=NULL){printf("已添加 #%d：%s\n",task->id,task
   ->name);}}else{puts( "用法：add <优先级> <名称>");}}else if(strcmp(command,"start")==0
    ||strcmp(command, "done")==0){if(sscanf(line+offset,"%d",&id)==1&&list_find(list,id)
     !=NULL){list_find( list,id)->state=command[0]=='s'?DOING:DONE;printf("#%d -> %s\n"
      , /*.*/ id,status_label( list_find(list,id)->state));}else{puts("找不到该任务"
       );}}else if(strcmp(command, "rm")==0){if(sscanf(line+offset,"%d",&id)==1&& //(
         list_remove(list,id)){printf( "已删除 #%d\n",id);}else{puts("找不到该任务"
          ) /*+*/ ;}}else if(strcmp(command, "ls")==0){list_print(list);}else //&.
            if(strcmp(command,"sum")==0){ list_summary(list);}else if(strcmp //:
              (command,"quit")==0){return 0;} else{printf("未知命令：%s\n" //o
                , /*)*/ command /*o*/ );}return 1;}int main(void){ TaskList
                   list;char line[MAX_LINE];list_init(&list);while( fgets
                      (line,sizeof line,stdin)!=NULL){trim_newline //+
                         (line );if(!handle(&list,line)){break; //+
                              }}list_summary(& list);list_free
                                    (&list);return 0;}
