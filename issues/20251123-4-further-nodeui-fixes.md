# Align the Session information components across lines. 

Basically allocate enough space probably based on the largest component string for each column or something like that. 

# Use colors in the session info display components smartly, make them easier to read. 

# For the action menus, use the longer helpful names of the actions that we have in the current rich UI. 

# For the action menu, also add a numeric jump. 

So number the actions and so people can just enter a number. In this case, we don't need double digit support. 

# session list - add line explaining (t), (c), (sub) annotations

In the main session list that is displayed, add an extra line below the keyboard shortcut hints that explains any of the session ID annotations. 

Also add a third line, perhaps that says what is being displayed, meaning all sessions or all sessions, except sub, etc. Again, this is something that is done in the rich UI currently, maybe to avoid code duplication, you could try to factor out these aspects so that these are need to be changed only in one place and maintained in one place. 



