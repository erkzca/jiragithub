# jiragithub
Here is some resources beforehand
For importing i am mostly using this since it allows me to set up specific time and assignee to the issue as the github original ones does not
https://gist.github.com/jonmagic/5282384165e0f86ef105

What is left for this to be done.

Well there is a small issue when importing too many comments with one api call.
The maximum request size is 1MB
We need to perform some handling for that and split it into multiple calls:
https://medium.com/@r_chan/tips-tricks-how-to-find-a-json-object-size-in-python-8c1f6d208dc1

Next thing that needs to be done is to find urls for images in comments. In normal call json we only receive links in attachment.
We can either try to create a function that will map by the name and make it as an href in that specific comment. 
Another way we can achieve this is to do additional call via xml and try to get the url from there and match with the comment it belongs to.
To get the call in xml simply update application/json to application/xml


Another thing worth mentioning is the assignee list and where did i get it from. Well it is from the their test repository.
For your initial testing in your own repository you dont have to worry about that as of yet. When the times comes we should ask them to provide
the list so we wont have to be guessing which person is who. Since some of the namings are not exactly the sames as in Jira.

I added quite some comments in the code to check what is what. Also removed some unecessary stuff that was left over.

Also more resouces:
https://docs.github.com/en/rest/issues/issues?apiVersion=2022-11-28#create-an-issue
https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/#about


