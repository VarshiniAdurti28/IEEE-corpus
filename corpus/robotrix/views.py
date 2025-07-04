from datetime import datetime

from accounts.models import User
from config.models import DATETIME_FORMAT
from config.models import ModuleConfiguration
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import redirect
from django.shortcuts import render
from robotrix.forms import AnnouncementForm
from robotrix.forms import InviteForm
from robotrix.forms import RobotrixForm
from robotrix.forms import TeamCreationForm
from robotrix.models import Announcement
from robotrix.models import Invite
from robotrix.models import RobotrixUser
from robotrix.models import Team

from corpus.decorators import ensure_group_membership
from corpus.decorators import module_enabled
from corpus.tasks import send_email_async


@module_enabled(module_name="robotrix")
def home(request):
    args = {}
    # Checking if user is Robotrix_admin group member
    if request.user.groups.filter(name="robotrix_admin").exists():
        args = {"admin": True}
    config = ModuleConfiguration.objects.get(module_name="robotrix").module_config

    try:
        if request.user.is_authenticated:
            robotrix_user = RobotrixUser.objects.get(user=request.user)
            args["registered"] = True
            args["robotrix_user"] = robotrix_user
    except RobotrixUser.DoesNotExist:
        args["registered"] = False

    reg_start_datetime, reg_end_datetime = (
        config["reg_start_datetime"],
        config["reg_end_datetime"],
    )

    reg_start_datetime, reg_end_datetime = datetime.strptime(
        reg_start_datetime, DATETIME_FORMAT
    ), datetime.strptime(reg_end_datetime, DATETIME_FORMAT)

    registration_active = (reg_start_datetime <= datetime.now()) and (
        datetime.now() <= reg_end_datetime
    )

    registration_done = reg_end_datetime < datetime.now()

    args["registration_active"] = registration_active
    args["registration_done"] = registration_done

    return render(
        request,
        "robotrix/home.html",
        args,
    )


@login_required
@module_enabled(module_name="robotrix")
def index(request):
    args = {}
    try:
        robotrix_user = RobotrixUser.objects.get(user=request.user)
        args["robotrix_user"] = robotrix_user
    except RobotrixUser.DoesNotExist:
        messages.error(request, "Please register for Robotrix first!")
        return redirect("robotrix_register")

    if robotrix_user.team is not None:
        args["in_team"] = True

        args["team_creation_form"] = TeamCreationForm(instance=robotrix_user.team)

        team = robotrix_user.team
        members = RobotrixUser.objects.filter(team=team)
        team_count = members.count()

        config = ModuleConfiguration.objects.get(module_name="robotrix").module_config

        max_count = int(config["max_team_size"])

        if team_count >= max_count:
            args["team_full"] = True
        if team.team_leader == robotrix_user:
            args["is_leader"] = True
            invites = Invite.objects.filter(inviting_team=team)
            args["invites_from_team"] = invites
            args["invite_form"] = InviteForm()
        else:
            args["is_leader"] = False

        args["team_count"] = team_count

        args["team"] = team
        args["members"] = members
        args["payment_status"] = team.payment_status

        pay_status = "Not Registered"

        if args["payment_status"] == "E" or args["payment_status"] == "P":
            pay_status = "Complete"
        elif args["payment_status"] == "U":
            pay_status = "Incomplete"

    else:
        args["in_team"] = False
        args["is_leader"] = False
        args["team_creation_form"] = TeamCreationForm()
        invites = Invite.objects.filter(invite_email=robotrix_user.user.email)
        args["invites_for_user"] = invites

    config = ModuleConfiguration.objects.get(module_name="robotrix").module_config

    reg_start_datetime, reg_end_datetime = (
        config["reg_start_datetime"],
        config["reg_end_datetime"],
    )

    reg_start_datetime, reg_end_datetime = datetime.strptime(
        reg_start_datetime, DATETIME_FORMAT
    ), datetime.strptime(reg_end_datetime, DATETIME_FORMAT)

    registration_active = (reg_start_datetime <= datetime.now()) and (
        datetime.now() <= reg_end_datetime
    )

    args["registration_active"] = registration_active

    try:
        if pay_status == "Complete":
            announcements = Announcement.objects.filter(
                announcement_type__in=["A", "P"]
            )
        elif pay_status == "Incomplete":
            announcements = Announcement.objects.filter(
                announcement_type__in=["A", "U"]
            )
        else:
            announcements = Announcement.objects.filter(
                announcement_type__in=["A", "N"]
            )
    except Exception:
        announcements = Announcement.objects.filter(announcement_type__in=["A", "N"])

    announcements = announcements.order_by("-date_created")

    args["announcements"] = announcements

    return render(request, "robotrix/index.html", args)


@login_required
@module_enabled(module_name="robotrix")
def register(request):
    config = ModuleConfiguration.objects.get(module_name="robotrix").module_config

    reg_start_datetime, reg_end_datetime = (
        config["reg_start_datetime"],
        config["reg_end_datetime"],
    )

    reg_start_datetime, reg_end_datetime = datetime.strptime(
        reg_start_datetime, DATETIME_FORMAT
    ), datetime.strptime(reg_end_datetime, DATETIME_FORMAT)

    registration_active = (reg_start_datetime <= datetime.now()) and (
        datetime.now() <= reg_end_datetime
    )

    if not registration_active:
        messages.error(request, "Registration for Robotrix is not active yet!")
        return redirect("index")

    try:
        robotrix_user = RobotrixUser.objects.get(user=request.user)
        messages.error(request, "You have already registered for Robotrix!")
        return redirect("robotrix_index")
    except RobotrixUser.DoesNotExist:
        pass

    if request.method == "POST":
        form = RobotrixForm(request.POST)
        if form.is_valid():
            robotrix_user = form.save(commit=False)
            robotrix_user.user = request.user
            robotrix_user.save()
            messages.success(request, "Successfully registered for Robotrix!")
            return redirect("robotrix_index")
        else:
            messages.error(request, "Please correct the errors before registering!")

    else:
        form = RobotrixForm()

    args = {"form": form}
    return render(request, "robotrix/register.html", args)


@login_required
@module_enabled(module_name="robotrix")
def create_team(request):
    if request.method == "POST":
        form = TeamCreationForm(request.POST)
        robotrix_user = RobotrixUser.objects.get(user=request.user)
        if robotrix_user.team is not None:
            if form.is_valid():
                team = robotrix_user.team
                team.team_name = form.cleaned_data["team_name"]
                team.save()
                messages.success(request, "Successfully updated team name!")
                return redirect("robotrix_index")
        else:
            if form.is_valid():
                team = form.save(commit=False)
                robotrix_user = RobotrixUser.objects.get(user=request.user)
                team.team_leader = robotrix_user

                if robotrix_user.from_nitk or robotrix_user.ieee_member:
                    team.payment_status = "E"
                else:
                    team.payment_status = "U"

                team.save()
                robotrix_user.team = team
                robotrix_user.save()
                messages.success(request, "Successfully created team!")
                return redirect("robotrix_index")
    else:
        messages.error(request, "Please correct the errors before creating team!")
        return redirect("robotrix_index")


@login_required
@module_enabled(module_name="robotrix")
def create_invite(request):
    robotrix_user = RobotrixUser.objects.get(user=request.user)
    if request.method == "POST":
        form = InviteForm(request.POST)
        if form.is_valid():
            if request.user.email == form.cleaned_data["invite_email"]:
                messages.error(request, "You cannot invite yourself!")
                return redirect("robotrix_index")

            try:
                user = User.objects.get(email=form.cleaned_data["invite_email"])
                invited_imp_user = RobotrixUser.objects.get(user=user)
                if invited_imp_user.team is not None:
                    messages.error(request, "User is already in a team!")
                    return redirect("robotrix_index")
            except (User.DoesNotExist, RobotrixUser.DoesNotExist):
                pass

            try:
                invite = Invite.objects.get(
                    inviting_team=robotrix_user.team,
                    invite_email=form.cleaned_data["invite_email"],
                )
                messages.error(request, "Invite has already been sent!")
                return redirect("robotrix_index")
            except Invite.DoesNotExist:
                pass

            invite_counts = Invite.objects.filter(
                inviting_team=robotrix_user.team
            ).count()

            team_members = RobotrixUser.objects.filter(team=robotrix_user.team).count()

            config = ModuleConfiguration.objects.get(
                module_name="robotrix"
            ).module_config
            max_count = int(config["max_team_size"])

            if invite_counts >= max_count or team_members >= max_count:
                messages.error(request, "Maximum team member limit reached!")
                return redirect("robotrix_index")

            invite = form.save(commit=False)
            inviting_team = robotrix_user.team
            invite.inviting_team = inviting_team
            invite.save()

            messages.success(request, "Invite sent!")
            return redirect("robotrix_index")
    messages.error(request, "Illegal Request")
    return redirect("robotrix_index")


@login_required
@module_enabled(module_name="robotrix")
def accept_invite(request, pk):
    invite = Invite.objects.get(pk=pk)
    team_members = RobotrixUser.objects.filter(team=invite.inviting_team).count()
    config = ModuleConfiguration.objects.get(module_name="robotrix").module_config
    max_count = int(config["max_team_size"])

    if team_members >= max_count:
        invite.delete()
        messages.error(request, "Maximum team member limit reached!")
        return redirect("robotrix_index")

    if request.user.email != invite.invite_email:
        messages.error(request, "Illegal request")
        return redirect("robotrix_index")

    robotrix_user = RobotrixUser.objects.get(user=request.user)
    robotrix_user.team = invite.inviting_team
    robotrix_user.save()

    if robotrix_user.from_nitk or robotrix_user.ieee_member:
        inviting_team = invite.inviting_team
        inviting_team.payment_status = "E"
        inviting_team.save()

    Invite.objects.filter(invite_email=request.user.email).delete()

    messages.success(request, "Invite accepted!")
    return redirect("robotrix_index")


@login_required
@module_enabled(module_name="robotrix")
def delete_invite(request, pk):
    invite = Invite.objects.get(pk=pk)
    invite.delete()

    messages.success(request, "Invite deleted!")
    return redirect("robotrix_index")


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def admin(request):
    return render(request, "robotrix/admin/admin.html", {})


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def team_management(request):
    args = {}
    args["teams"] = Team.objects.all()
    return render(request, "robotrix/admin/teams.html", args)


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def team_page(request, pk):
    args = {}
    team = Team.objects.get(pk=pk)
    args["team"] = team
    args["members"] = RobotrixUser.objects.filter(team=team)
    return render(request, "robotrix/admin/team_page.html", args)


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def user_management(request):
    args = {}
    users = RobotrixUser.objects.all()

    nitk_count = users.values("from_nitk").annotate(count=Count("from_nitk"))
    ieee_count = users.values("ieee_member").annotate(count=Count("ieee_member"))

    args = {
        "users": users,
        "nitk_count": nitk_count,
        "ieee_count": ieee_count,
    }
    return render(request, "robotrix/admin/users.html", args)


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def announcements_management(request):
    if request.method == "POST":
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            announcement = form.save()

            mail_option = form.cleaned_data.get("announcement_mailing", "1")
            email_ids = None
            if mail_option == "2":
                # just for team leaders
                if announcement.announcement_type == "A":
                    email_ids = list(
                        Team.objects.values_list("team_leader__user__email", flat=True)
                    )
                elif announcement.announcement_type == "P":
                    email_ids = list(
                        Team.objects.filter(payment_status__in=["P", "E"]).values_list(
                            "team_leader__user__email", flat=True
                        )
                    )
                elif announcement.announcement_type == "U":
                    email_ids = list(
                        Team.objects.filter(payment_status="U").values_list(
                            "team_leader__user__email", flat=True
                        )
                    )
            elif mail_option == "3":
                # for all members
                if announcement.announcement_type == "A":
                    email_ids = list(
                        RobotrixUser.objects.values_list("user__email", flat=True)
                    )
                elif announcement.announcement_type == "P":
                    email_ids = list(
                        # send to both paid and exempted teams
                        RobotrixUser.objects.filter(
                            team__payment_status__in=["P", "E"]
                        ).values_list("user__email", flat=True)
                    )
                elif announcement.announcement_type == "U":
                    email_ids = list(
                        RobotrixUser.objects.filter(
                            team__payment_status="U"
                        ).values_list("user__email", flat=True)
                    )
                elif announcement.announcement_type == "N":
                    email_ids = list(
                        RobotrixUser.objects.filter(team=None).values_list(
                            "user__email", flat=True
                        )
                    )
                elif announcement.announcement_type == "NI":
                    # all users who have not registered for robotrix
                    users = User.objects.exclude(
                        email__in=RobotrixUser.objects.values_list(
                            "user__email", flat=True
                        )
                    )

                    users = users.exclude(
                        email__in=[
                            "robotrix_admin",
                            "embedathon_admin",
                        ]
                    )
                    users = users.exclude(is_staff=True)
                    users = users.exclude(is_superuser=True)

                    email_ids = list(users.values_list("email", flat=True))

            if email_ids is not None:
                send_email_async.delay(
                    "Announcement | Robotrix",
                    "emails/robotrix/announcement.html",
                    {"announcement": announcement},
                    bcc=email_ids,
                )

            messages.success(request, "Successfully created announcement!")
            return redirect("robotrix_announcements")
        else:
            messages.error(
                request, "Please correct the errors before creating announcement!"
            )
            return redirect("robotrix_announcements")
    else:
        form = AnnouncementForm()
        announcements = Announcement.objects.all().order_by("-date_created")

    args = {"form": form, "announcements": announcements}
    return render(request, "robotrix/admin/announcements.html", args)


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def delete_announcement(request, pk):
    announcement = Announcement.objects.get(pk=pk)
    announcement.delete()
    messages.success(request, "Successfully deleted announcement!")
    return redirect("robotrix_announcements")


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def mark_payment_complete(request, pk):
    team = Team.objects.get(pk=pk)
    team.payment_status = "P"
    team.save()
    payment_status = "Complete"
    final_message = "Thanks for registering for Robotrix."
    for member in RobotrixUser.objects.filter(team=team):
        if member.user.email is not None:
            send_email_async.delay(
                "Payment Complete | Robotrix",
                "emails/robotrix/payment_complete.html",
                {
                    "team": team,
                    "user": member.user,
                    "payment_status": payment_status,
                    "final_message": final_message,
                },
                bcc=[member.user.email],
            )
    messages.success(
        request, "Successfully marked payment as complete and sent emails!"
    )
    return redirect("robotrix_admin_team_page", pk=pk)


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def mark_payment_incomplete(request, pk):
    team = Team.objects.get(pk=pk)
    team.payment_status = "U"
    team.save()
    payment_status = "Incomplete"
    final_message = "Please contact us if you have any questions."
    for member in RobotrixUser.objects.filter(team=team):
        if member.user.email is not None:
            send_email_async.delay(
                "Payment Incomplete | Robotrix",
                "emails/robotrix/payment_incomplete.html",
                {
                    "team": team,
                    "user": member.user,
                    "payment_status": payment_status,
                    "final_message": final_message,
                },
                bcc=[member.user.email],
            )
    messages.success(request, "Successfully marked payment as incomplete!")
    return redirect("robotrix_admin_team_page", pk=pk)


@login_required
@ensure_group_membership(group_names=["robotrix_admin"])
def team_download(request):
    import csv
    from django.http import HttpResponse

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="teams.csv"'

    writer = csv.writer(response)
    writer.writerow(["First Name", "Last Name", "Email", "Phone Number"])

    for team in Team.objects.filter(payment_status__in=["P", "E"]):
        leader = team.team_leader
        writer.writerow(
            [
                leader.user.first_name,
                leader.user.last_name,
                leader.user.email,
                leader.user.phone_no,
            ]
        )

    return response
