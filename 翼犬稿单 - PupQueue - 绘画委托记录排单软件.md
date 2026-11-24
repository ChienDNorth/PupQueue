# 翼犬稿单 - PupQueue - 绘画委托记录排单软件

## Needs to be aware of 

You need to use github/git to push and pull, write down all the version and branches

Program use python to write

The project always use ponytail and karpathy-guidelines as skills and guidelinesb, and they needs to be activated all the time

The project should have both english and chinese version, build up to have a choice of language and possibly have more languages in the future

The project will link to google calendar api in the future version, aim to record all the past timespend for each task and the plans for the future

## Main function

### V1 The main commission queue system

We first build english version, but leave a setting part that can change the language to chinese or other language(in the future)

The main function looks like reclaim.ai 2.0 or Motion, but with artist commission queue specified.

basic functions:

1. basic task todo list functions: add todo list, detele task , snooze task

2. Task todo list should have: 

   - **drawing task types**(optional)(Gift, Self Project, Drawing Swap, Commission, else, and allow people to personalize the types like add or delete)

   - **priority**(like jira: Highest, High, Medium, Low, and Lowest, user can change the default setting of this one)
   - **price**(optional, can leave blank)
   - **Payed?**(checkbox, optional, if the user choose payed, there should be showing extra boxes that can write down the payment and payed time and the amount of payed money)
   - **estimated time** (optional, user can type in minutes(min), hours(h) and day(d) to writing into the system, it needs all translate into the regular time count, like 70min should be writing in the system as 1h10min, and 0.5h should writing into the system as 30min, 24h is 1 day, and such)
   - **due date (and time)** (optional, will pull out a calendar for user to choose, but user can also type in the date and time)
   - **Client Contacts** (Optional, have infos like client's name, email, social medias, for social medias, it gave user customized choice to choose from a list, and user can editing the list of choices, like QQ, Twitter, Vgen, Mihuashi and such)
   - **Other Information** ( optional, leave a text box that can add photos also, for artist to write down the information of clients' requests) (photo that uploaded should be save under the same directory as the program, and have a directory inside this root directory called "photos")

3. all the tasks are saved in one csv file (or if its too big, automatically open a new csv file), the information should have all that listed plus if there is photos, save the photo path in that list of csv queues. csv file save under the directory under root directory called task records. tasks that finished(completed) should save in a different csv file than unfinished one.
4. there is a page that shows all the import tasks, and can be filtered by priority, price, payed or not, drawing task types or estimated time. for example, it can show only the highest priority, or show from high priority to lower priorities
5. there is a workflow page like jira or vgen artist dashboard, that can drag the tasks around into under the Waitlist, Ready, WIP, and completed, default is either Waitlist(unpayed commission), or ready(payed commission or other kind thats not a commission)





### V1.1 Updates

1. Add price currency choice, in the setting the user can select the default currency (which should be USD for english user and CNY for chinese user)
2.  when typing in estimated time, after finished typing, auto translate the number into the right form and show it, for example 90min is 1h30min, when i type in 90min it auto translate into 1h30min, and when i didnt type if its min or h or day, default is min
3. Due date and time, the default time should be the full hours like 1:00pm, 2:00pm and such, it should'nt be 2:49pm like with the 49min there. Set the default time to 12am(user can change it in the settings)
4. Make the due date choosing page prettier
5. Make the page of adding task more organized, like write several catogory of the information. likeTitle, Basic information(drawing type, price, paid), Time (estimated time, due), client information(client name, client email, socialmedia, other information, photos(change photos to reference photos))
6. priority bar can move to the top right corner of the new task window, using icons to show its priority, with add on text showing which priority is which
7. client email needs to be the right form or it wont go through (like have to with @ and other standards for an email)
8. user can click in the task and see the detail information of the task, when click it shows another bar on the right hand side and shows all the details
9. auto zoom-in the page depending on how user's monitor screensize is, so the text wont be too small, it should be the right size and pretty
10. it didnt save the photos that uploaded to the program successfully, it should under ./task_records/photos. also, change task records directory into task_records
11. show the version on the bottom of the page, writing author's name 北原啸ChienDNorth, and year 2026
12. do the setting for git, and publish a branch



### V 1.2

1. Bug fix: when uploaded a photo(edited the task), the theme auto changed back to the dark mode, instead of keeping the light mode i settled
2. i want the photo that saved at local using the name of the title, so its easier to track.
3. after delete the task or photo, the local one should be gone too, but if the task is finished, move the photo to directory finished_task_photos under photo directory, instead of detele it
4. add a function in settings that can delete all the finished photos, to clear up space
5. the preview window that shows in the queue and board for each task needs to be more organized, right now the window is pretty ugly
6. thrink the edit, snooze button and delete button a little bit, they are too big rn, and re-organize the whole page so different text have organized size
7. put language setting button on the top right corner or all pages, so its more obivious
8. snooze 1 day change to snooze button, and when you click you can have different options like snooze 1 hour, snooze 2hours, snooze 1day, snooze2 days. snooze 7 days, and custom snooze. add a button to cancel the snooze for already snoozed tasks



### V 1.3

1. reorganize settings
2. settings should be have a category on the left that can choose different type of settings, instead of all just on a long list
3. delete priorities personalization in settings, but still have the default priority settings
4. all the choices in the lists should be prettier, like you can type in one and it add to the list as individual tags that can be edited or delete, not a whole text list
5. add a local file that save the settings, and user can look at the file or upload a setting file to get the presets





###  V2.0

1. enter button shouldn't be just immediatly create a task, it should only be finishing its individual box of information. Shift+enter is creating the task
2. add a shortcut settings
3. add a button Mark Done on the bottom of each tasks, to complete the task, it should have the text and an icon, the icon is attached to the chat, done_icon_1 is when the user havent click Mark Done, where done_icon_2 is when user click done. 
4. when user click done, wait for 7 seconds and move the task to finished list, showing an bar that count down the time(a string bar that gets shorter), if user click the mark done button again, stop the process, so dont move the task to the finished list, stay the old same
5. add a check bar option to check all the finished tasks in the filter



# V 2.1 Updates

Change the color for the board, each parts like waitlist, ready, wip and complete have its own backrground color(not the task, its the background) so its easily distinguished, the color needs to fit the theme