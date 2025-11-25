A lot of the issues below are because you are implementing the node UI to mirror what we are already doing in the rich UI, but you're creating fresh code for this, which is a reason for the divergence. If we were somehow refactoring the rich UI code so that we can use that same back end fragments somehow here, then there will be less of that issue.

So all of the below are because of creating fresh code paths. The most critical thing here is for you to think about how you might design this and communicate to me how you will plan this. 

The node UI should have the same helpful hints, etc. that we have in the rich UI. So I want you to basically study the rich UI in detail or how the various menus are presenting information and reflect all of that exactly in this node based menu. Below are specific things that need to be fixed, but you may surface other things when you study the rich based UI. 


# group the action menu items into non-launch, launch actions

The first three actions should be non-launch actions, and the next three should be launch actions, meaning they do some kind of a resume of session. This is exactly how we are ordering them in the current rich based UI. So you should look at how we are doing it there. And also hopefully we should we are not duplicating any business logic. You should simply refer to how they are ordered in the current Rich UI.

Maybe you can factor out that functionality. 
Important, let me know how you are going to be designing this because I don't want to have a lot of code duplication. It makes things harder to maintain. 

# EXPORT action - accept Empty destination file path and use default. 

This is exactly how we do in the current rich UI, where if the user does not enter a path, it uses the default path. This is yet another case where having parallel
code paths (i.e. in node ui and rich ui) is causing divergence. 


# EXPORT ACtion - There should be a clear indicator of where to type the path 

because right now the way it looks, it's unclear where we should type the path because it simply shows a prompt saying destination type path. But that's a bit confusing. So maybe have a box there with a blinking cursor and if that is not hard to do and then have that box be expandable, meaning however long the path might be, it will take that or just show a blinking cursor.

We don't need a box, so at least it's clear where to type. Or if you want to make it even simpler, instead of saying destination colon type path, which is very cryptic, you can say enter path of file to export to, and you should give the same hints that we are giving in the rich UI. Meaning you have to say that it should be a doc txt file.

Again, refer to how the rich UI is doing it. 

# COPY action - same issue as above for Export action - Make it clear where to type the path


