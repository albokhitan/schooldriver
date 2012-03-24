#   Copyright 2011 David M Burke
#   Author David M Burke <david@burkesoftware.com>
#   
#   This program is free software; you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation; either version 2 of the License, or
#   (at your option) any later version.
#     
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#      
#   You should have received a copy of the GNU General Public License
#   along with this program; if not, write to the Free Software
#   Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#   MA 02110-1301, USA.

from django.shortcuts import render_to_response, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test, permission_required
from django.contrib.auth import authenticate, login, logout
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE
from django.core.urlresolvers import reverse
from django.template import RequestContext
from django.http import HttpResponse, HttpResponseRedirect
from django.forms.formsets import formset_factory
from django.forms.models import BaseModelFormSet, modelformset_factory
from django.db.models import Q, Sum, Count, get_model
from django.contrib.contenttypes.models import ContentType
from django.views.decorators.csrf import csrf_exempt
from django.utils.safestring import mark_safe

from ecwsp.administration.models import *
from ecwsp.sis.models import *
from ecwsp.sis.forms import *
from ecwsp.sis.report import *
from ecwsp.schedule.models import *
from ecwsp.schedule.calendar import *
from ecwsp.work_study.models import StudentWorker, TimeSheet
from ecwsp.sis.xlsReport import *

from ajax_select.fields import AutoCompleteSelectMultipleField, AutoCompleteSelectField
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import cm
import xlwt
from tempfile import mkstemp
from datetime import date
import sys
import httpagentparser

@login_required
def user_preferences(request):
    profile = UserPreference.objects.get_or_create(user=request.user)[0]
    if request.POST:
        form = UserPreferenceForm(request.POST, instance=profile)
        if form.is_valid():
            form.cleaned_data['user'] = request.user
            form.save()
            messages.info(request, 'Successfully updated preferences')
            if 'refer' in request.GET and request.GET['refer']:
                return HttpResponseRedirect(request.GET['refer'])
            return HttpResponseRedirect(reverse('admin:index'))
    else:
        form = UserPreferenceForm(instance=profile)
    return render_to_response('sis/user_preferences.html', {
        'form': form,
    }, RequestContext(request, {}),)


@login_required
def index(request):
    """if student, redirect them to timesheet.  if faculty allow this page
    """
    if request.user.groups.filter(Q(name='faculty') | Q(name='viewer')).count() > 0:
        try:
            # Warn users of IE and Firefox < 4.0 they are not supported
            ua = request.META['HTTP_USER_AGENT']
            browser_name = httpagentparser.detect(ua)['browser']['name']
            browser_version = httpagentparser.detect(ua)['browser']['version']
            if browser_name == "Microsoft Internet Explorer":
                messages.warning(request,
                    mark_safe('Warning Internet Explorer is not supported on the admin site. If you have any trouble, try using a standards compliant browser such as Firefox, Chrome, Opera, or Safari.'))
            elif browser_name == "Firefox" and int(browser_version[0]) < 4 :
                messages.warning(request, 'Warning, your version of Firefox is out of date. Please upgrade.')
        except:
            pass    
        return HttpResponseRedirect('/admin')
    elif request.user.groups.filter(Q(name='students')).count() > 0:
        return student_redirect(request)
    elif request.user.groups.filter(Q(name='company')).count() > 0:
        from ecwsp.work_study.views import supervisor_dash
        return supervisor_dash(request)
    else:
        return render_to_response('base.html', {'msg': "Not authorized", 'request': request,}, RequestContext(request, {}))

def student_redirect(request):
    """ Redirects student to proper page based on what's installed and if it's possible to display the timesheet """
    if 'ecwsp.work_study' in settings.INSTALLED_APPS:
        from ecwsp.work_study.views import student_timesheet
        from ecwsp.work_study.models import StudentWorker
        try:
            student = StudentWorker.objects.get(username=request.user.username)
        except StudentWorker.DoesNotExist:
            student = None
        if student and hasattr(student, 'placement') and student.placement:
            return student_timesheet(request)
    return render_to_response('base.html', {'msg': "Welcome!", 'student': 'student', 'request': request,}, RequestContext(request, {}))

@user_passes_test(lambda u: u.groups.filter(name='registrar').count() > 0 or u.is_superuser, login_url='/')
def import_everything(request):
    if request.POST:
        form = UploadFileForm(request.POST, request.FILES)
        if form.is_valid():
            from ecwsp.sis.importer import Importer
            importer = Importer(request.FILES['file'], request.user)
            msg = ""
            msg_to_add, filename = importer.magic_import_everything()
            msg += msg_to_add
            form = UploadFileForm()
            return render_to_response('upload.html', {'form': form, 'msg': msg, 'error_filename':filename, 'request': request,})
        else:
            return render_to_response('upload.html', {'form': form, 'request': request,})
    form = UploadFileForm()
    return render_to_response('upload.html', {'form': form, 'request': request,}, RequestContext(request, {}))
    

@user_passes_test(lambda u: u.has_perm("sis.view_student"), login_url='/')    
def photo_flash_card(request, year=None):
    students = Student.objects.filter(inactive=False)
    grade_levels = GradeLevel.objects.all()
    try:
        if request.POST:
            form = StudentLookupForm(request.POST, request.FILES)
            if form.is_valid():
                id = form.cleaned_data['student']
            else:
                id = students.order_by('?')[0].pk
        else:
            form = StudentLookupForm()
            if year:
                id = students.filter(year=GradeLevel.objects.get(id=year)).order_by('?')[0].pk
            else:
                id = students.order_by('?')[0].pk
        student = Student.objects.filter(inactive=False).get(pk=id)
    except:
        messages.error(request, 'Student not found')
        return HttpResponseRedirect(reverse('admin:index'))
    return render_to_response('sis/flashcard.html', {'form': form, 'student_name': student, 'grade_levels':grade_levels, 'student_img': student.pic.url_530x400, 'request': request}, RequestContext(request, {}))

@user_passes_test(lambda u: u.has_perm("sis.view_student"), login_url='/')  
def transcript_nonofficial(request, id):
    student = Student.objects.filter(id=id)
    template = Template.objects.get_or_create(name="Transcript Nonoffical")[0]
    if template.file:
        template = template.file.path
        format = 'pdf'
        options = {
            'date': date.today(),
            'student': student,
        }
        return pod_report_grade(template, transcript=True, options=options, students=student, format=format)
        
    messages.info(request, 'Please upload a templated called "Transcript Nonoffical"')
    return HttpResponseRedirect(reverse('admin:index'))
    
    form = StudentReportWriterForm(request.POST, request.FILES)
    data = form.cleaned_data
    if data['template']:
        # use selected template
        template = data['template']
        template = template.file.path
    else:
        # or use uploaded template, saving it to temp file
        template = request.FILES['upload_template']
        tmpfile = mkstemp()[1]
        f = open(tmpfile, 'wb')
        f.write(template.read())
        f.close()
        template = tmpfile
    format = UserPreference.objects.get_or_create(user=request.user)[0].get_format(type="document")
    if 'pod_report_transcript' in request.POST:
        transcript = True
    else:
        transcript = False
    return pod_report_grade(template, transcript=transcript, options=data, students=form.get_students(data), format=format)


@permission_required('sis.reports') 
def school_report_builder_view(request, report=None):
    if request.method == 'POST':
        if 'thumbs_fresh' in request.POST:
            return student_thumbnail(request, GradeLevel.objects.get(id=9))
        elif 'thumbs_soph' in request.POST:
            return student_thumbnail(request, GradeLevel.objects.get(id=10))
        elif 'thumbs_jun' in request.POST:
            return student_thumbnail(request, GradeLevel.objects.get(id=11))
        elif 'thumbs_sen' in request.POST:
            return student_thumbnail(request, GradeLevel.objects.get(id=12))
        elif 'p_attendance' in request.POST:
            format = UserPreference.objects.get_or_create(user=request.user)[0].get_format(type="document")
            if request.POST['p_attendance'] == "Monday":
                day = "1"
            if request.POST['p_attendance'] == "Tuesday":
                day = "2"
            if request.POST['p_attendance'] == "Wednesday":
                day = "3"
            if request.POST['p_attendance'] == "Thursday":
                day = "4"
            if request.POST['p_attendance'] == "Friday":
                day = "5"
            return pod_report_paper_attendance(day, format=format)
        elif 'pod_report' in request.POST:
            form = StudentReportWriterForm(request.POST, request.FILES)
            if form.is_valid():
                data = form.cleaned_data
                if data['template']:
                    # use selected template
                    template = data['template']
                    template = template.get_template_path(request)
                    if not template:
                        return render_to_response('sis/reportBuilder.html', {'request':request, 'form':form}, RequestContext(request, {}))
                else:
                    # or use uploaded template, saving it to temp file
                    template = request.FILES['upload_template']
                    tmpfile = mkstemp()[1]
                    f = open(tmpfile, 'wb')
                    f.write(template.read())
                    f.close()
                    template = tmpfile
                format = UserPreference.objects.get_or_create(user=request.user)[0].get_format(type="document")
                return pod_report_all(template, options=data, students=form.get_students(data), format=format)
            else:
                return render_to_response('sis/reportBuilder.html', {'request':request, 'form':form})
    else:
        form = StudentReportWriterForm()
        form.fields['template'].queryset = Template.objects.filter(general_student=True)
        return render_to_response('sis/reportBuilder.html', {'request':request, 'form':form}, RequestContext(request, {}))


@user_passes_test(lambda u: u.has_perm('sis.view_student'), login_url='/')      
def student_thumbnail(request, year):
    response = HttpResponse(mimetype="application/pdf")
    response['Content-Disposition'] = 'attachment; filename=%s' % "thumbnails.pdf"
    
    c = canvas.Canvas(response, pagesize=letter)  
    
    students = Student.objects.filter(year=year).order_by('lname', 'fname')
    xsize = 6*cm
    ysize = 4.5*cm
    dx = .7*cm + xsize    #space between each pic
    dy = 2*cm + ysize
    x = 1*cm            # starting locations
    y = 1*cm
    xn = 0                # counters
    yn = 0
    paper_height = 23*cm
    for stu in students:
        try:    
            if stu.pic:
                c.drawImage(unicode(settings.MEDIA_ROOT[:-7] + unicode(stu.pic.url_530x400)), x, paper_height - (y-.4*cm), xsize, ysize, preserveAspectRatio=True)
            else:
                c.drawString(x, paper_height - (y+.5*cm), "No Image")
            c.drawString(x, paper_height - y, unicode(stu))
            if xn < 2:
                x += dx
                xn += 1
            else:
                x = 1*cm
                xn = 0
                if yn < 3:
                    y += dy
                    yn += 1
                else:
                    y = 1*cm
                    yn = 0
                    c.showPage()  
        except:
            print >> sys.stderr, str(sys.exc_info()[0])
    c.showPage()  
    c.save()
    return response


def logout_view(request):
    logout(request)
    return render_to_response('base.html', {'msg': "You have been logged out.",}, RequestContext(request, {}))


@user_passes_test(lambda u: u.groups.filter(name='faculty').count() > 0 or u.is_superuser, login_url='/')
def student_page_redirect(request, id):
    """ Redirects user to highest level of permission they have for a student """
    try: from work_study.models import StudentWorker
    except: pass
    if request.user.has_perm(StudentWorker):
        return HttpResponseRedirect(reverse('admin:work_study_studentworker_change', args=(id,)))
    return HttpResponseRedirect(reverse('admin:sis_student_change', args=(id,)))

@permission_required('sis.change_student')
def import_naviance(request):
    msg = 'Import a test directly from Naviance such as SAT and ACT. You must have unique id (SWORD) and hs_student_id (Naviance) be the same. You must have already set up the <a href="/admin/schedule/standardtest/"> tests </a> <br/>' +\
        'In Naviance, click setup, then Import/Export then export the test you want. At this time only SAT and ACT is supported.'
    if request.method == 'POST':
        form = UploadNaviance(request.POST, request.FILES)
        if form.is_valid():
            test = form.cleaned_data['test']
            from ecwsp.sis.importer import Importer
            importer = Importer(file=form.cleaned_data['import_file'], user=request.user)
            msg, filename = importer.import_just_standard_test(test)
            msg += '<br/><a href="/media/import_error.xls">Download Errors</a>'
    else:
        form = UploadNaviance()
    msg = mark_safe(msg)
    return render_to_response('sis/generic_form.html', {'form':form,'msg':msg}, RequestContext(request, {}),)

@user_passes_test(lambda u: u.groups.filter(name="registrar").count() or u.has_perm('sis.reports') or u.is_superuser, login_url='/')   
def grade_report(request):
    form = StudentGradeReportWriterForm()
    mp_form = MarkingPeriodForm()
    
    if request.method == 'POST':
        if 'student_grade' in request.POST:
            form = StudentGradeReportWriterForm(request.POST, request.FILES)
            if form.is_valid():
                data = form.cleaned_data
                if data['template']:
                    # use selected template
                    template = data['template']
                    template_path = template.get_template_path(request)
                    if not template_path:
                        form.fields['template'].queryset = Template.objects.filter(Q(report_card=True) | Q(transcript=True))
                        return render_to_response('sis/grade_report.html', {'form':form, 'mp_form':mp_form}, RequestContext(request, {}),)
                    report_card = template.report_card
                    transcript = template.transcript
                else:
                    # or use uploaded template, saving it to temp file
                    template = request.FILES['upload_template']
                    tmpfile = mkstemp()[1]
                    f = open(tmpfile, 'wb')
                    f.write(template.read())
                    f.close()
                    template_path = tmpfile
                    report_card = True
                    transcript = True
                format = UserPreference.objects.get_or_create(user=request.user)[0].get_format(type="document")
                return pod_report_grade(template_path, options=data, students=form.get_students(data), format=format, report_card=report_card, transcript=transcript)
        elif 'aggregate_grade_report' in request.POST:
            from ecwsp.grades.models import Grade
            form = MarkingPeriodForm(request.POST)
            if form.is_valid():
                mps = form.cleaned_data['marking_period']
                data = []
                titles = ["Teacher", "Range", "No. Students", ""]
                for level in GradeLevel.objects.all():
                    titles += [level, ""]
                ranges = [['100', '90'], ['89.99', '80'], ['79.99', '70'], ['69.99', '60'], ['59.99', '50'], ['49.99', '0']]
                letter_ranges = ['P', 'F']
                for teacher in Faculty.objects.filter(course__marking_period__in=mps).distinct():
                    data.append([teacher])
                    grades = Grade.objects.filter(
                        marking_period__in=mps,
                        course__teacher=teacher,
                        student__inactive=False,
                        final=True,
                        override_final=False,
                    ).filter(
                        Q(grade__isnull=False) |
                        Q(letter_grade__isnull=False)
                    )
                    teacher_students_no = grades.distinct().count()
                    if teacher_students_no:
                        for range in ranges:
                            no_students = grades.filter(
                                    grade__range=(range[1],range[0]),
                                ).distinct().count()
                            percent = float(no_students) / float(teacher_students_no)
                            percent = ('%.2f' % (percent * 100,)).rstrip('0').rstrip('.') + "%"
                            row = ["", str(range[1]) + " to " + str(range[0]), no_students, percent]
                            for level in GradeLevel.objects.all():
                                no_students = grades.filter(
                                        grade__range=(range[1],range[0]),
                                        student__year__in=[level],
                                    ).distinct().count()
                                level_students_no = grades.filter(
                                        student__year__in=[level],
                                    ).distinct().count()
                                percent = ""
                                if level_students_no:
                                    percent = float(no_students) / float(level_students_no)
                                    percent = ('%.2f' % (percent * 100,)).rstrip('0').rstrip('.') + "%"
                                row += [no_students, percent]
                            data.append(row)
                        for range in letter_ranges:
                            no_students = grades.filter(
                                    letter_grade=range,
                                ).distinct().count()
                            if teacher_students_no:
                                percent = float(no_students) / float(teacher_students_no)
                                percent = ('%.2f' % (percent * 100,)).rstrip('0').rstrip('.') + "%"
                            else:
                                percent = ""
                            row = ["", str(range), no_students, percent]
                            for level in GradeLevel.objects.all():
                                no_students = grades.filter(
                                        letter_grade=range,
                                        student__year__in=[level],
                                    ).distinct().count()
                                level_students_no = grades.filter(
                                        student__year__in=[level],
                                    ).distinct().count()
                                if level_students_no:
                                    percent = float(no_students) / float(level_students_no)
                                    percent = ('%.2f' % (percent * 100,)).rstrip('0').rstrip('.') + "%"
                                else:
                                    percent = ""
                                row += [no_students, percent]
                            data.append(row)
                report = xlsReport(data, titles, "aggregate_grade_report.xls", heading="Teacher aggregate")
                
                passing = 70
                data = []
                titles = ['Grade']
                for dept in Department.objects.all():
                    titles.append(dept)
                    titles.append('')
                for level in GradeLevel.objects.all():
                    row = [level]
                    for dept in Department.objects.all():
                        fails = Grade.objects.filter(
                            marking_period__in=mps,
                            course__department=dept,
                            student__inactive=False,
                            student__year__in=[level],   # Shouldn't need __in. Makes no sense at all.
                            grade__lt=passing,
                            final=True,
                            override_final=False,
                        ).count()
                        total = Grade.objects.filter(
                            marking_period__in=mps,
                            course__department=dept,
                            student__inactive=False,
                            student__year__in=[level],
                            final=True,
                            override_final=False,
                        ).count()
                        if total:
                            percent = float(fails) / float(total)
                        else:
                            percent = 0
                        percent = ('%.2f' % (percent * 100,)).rstrip('0').rstrip('.')
                        row.append(fails)
                        row.append(percent)
                    data.append(row)
                report.addSheet(data, titles=titles, heading="Class Dept aggregate")
                return report.finish()
    form.fields['template'].queryset = Template.objects.filter(Q(report_card=True) | Q(transcript=True))
    return render_to_response('sis/grade_report.html', {'form':form, 'mp_form':mp_form}, RequestContext(request, {}),)
    
@user_passes_test(lambda u: u.has_perm("sis.view_student"), login_url='/')   
def view_student(request, id=None):
    student = None
    show_grades = False
    if request.method == 'POST':
        form = StudentLookupForm(request.POST)
        if form.is_valid():
            student = Student.objects.get(id=form.cleaned_data['student'].id)
    elif request.method == 'GET':
        try:
            form = StudentLookupForm(request.GET)
            if form.is_valid():
                student = Student.objects.get(id=form.cleaned_data['student'].id)
            if request.GET['show_grades']:
                show_grades = True
        except: pass
    if 'include_deleted' in request.GET:
        form = DeletedStudentLookupForm()
        include_deleted = True
    else:
        form = StudentLookupForm()
        include_deleted = False
    today = date.today()
    if student:
        emergency_contacts = student.emergency_contacts.all()
        siblings = student.siblings.all()
        cohorts = student.cohorts.all()
        numbers = student.studentnumber_set.all()
        
        # Schedule
        cal = Calendar()
        try:
            location = cal.find_student(student)
        except:
            location = None
            print >> sys.stderr, str(sys.exc_info()[0])
        # Guess the mp desired (current or next coming)
        current_mp = MarkingPeriod.objects.filter(end_date__gte=today).order_by('-start_date')
        if current_mp:
            current_mp = current_mp[0]
            schedule_days, periods = cal.build_schedule(student, current_mp, include_asp=True, only_active = True)
        else:
            schedule_days = None
            periods = None
        
        # Discipline
        if 'ecwsp.discipline' in settings.INSTALLED_APPS:
            disciplines = student.studentdiscipline_set.all()
        else:
            disciplines = None
        attendances = student.student_attn.all()
        
        # Alumni
        if hasattr(student, 'alumni') and request.user.has_perm("alumni.view_alumni"):
            alumni = student.alumni
        else:
            alumni = None
        
        #### CWSP related
        try:
            clientvisits = student.studentworker.clientvisit_set.all()
        except: clientvisits = None
        try:
            company_histories = student.studentworker.companyhistory_set.all()
        except:company_histories = None
        try:
            timesheets = student.studentworker.timesheet_set.exclude(Q(performance__isnull=True) | Q(performance__exact=''))
        except: timesheets = None
        try:
            if request.user.has_perm("sis.view_mentor_student"):
                student_interactions = student.studentworker.studentinteraction_set.all()
            else:
                student_interactions = None
        except:
            student_interactions = None
        try:
            supervisors = student.studentworker.placement.contacts.all()
        except:
            supervisors = None
        ########################################################################
        
        years = SchoolYear.objects.filter(markingperiod__course__courseenrollment__user=student).distinct()
        from ecwsp.grades.models import Grade
        for year in years:
            year.mps = MarkingPeriod.objects.filter(course__courseenrollment__user=student, school_year=year).distinct().order_by("start_date")
            year.courses = Course.objects.filter(courseenrollment__user=student, graded=True, marking_period__school_year=year).distinct()
            for course in year.courses:
                # Too much logic for the template here, so just generate html.
                course.grade_html = ""
                for mp in year.mps:
                    try:
                        course.grade_html += '<td> %s </td>' % (Grade.objects.get(student=student, final=True, course=course, marking_period=mp).get_grade(),)
                    except:
                        course.grade_html += '<td> </td>'
                course.grade_html += '<td> %s </td>' % (unicode(course.get_final_grade(student)),)
                
        return render_to_response('sis/view_student.html', {'form':form, 'show_grades':show_grades, 'date':today, 'student':student, 'emergency_contacts': emergency_contacts,
                                                        'siblings': siblings, 'numbers':numbers, 'location':location, 'disciplines':disciplines, 'attendances':attendances,
                                                        'student_interactions': student_interactions, 'clientvisits':clientvisits, 'supervisors':supervisors,
                                                        'company_histories':company_histories, 'timesheets':timesheets, 'years': years,
                                                        'include_deleted': include_deleted, 'current_mp': current_mp, 'schedule_days':schedule_days,
                                                        'alumni': alumni, 'periods': periods,}, RequestContext(request, {}),)
    return render_to_response('sis/view_student.html', {'form':form, 'include_deleted': include_deleted}, RequestContext(request, {}),)
